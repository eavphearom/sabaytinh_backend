"""Short database transactions, fenced leases, and durable notification markers."""
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4
import logging

from flask import current_app
from sqlalchemy import select

from app.exceptions.api_exception import BadRequestException, ResourceNotFoundException
from app.extensions import db
from app.models import Payment, Order, Invoice, OrderItem, OrderStatusHistory
from app.schemas.order_schema import PaymentResponseSchema
from app.services.payments.payment_strategy import GatewayError, PaymentContext, GatewayResult
from app.services.variant_stock_service import VariantStockService
from app.utils.date_util import DateUtil


logger = logging.getLogger(__name__)


class PaymentStateService:
    NOTIFICATION_STATES = ("PAID_NOTIFY_PENDING", "REFUND_REVIEW_NOTIFY_PENDING")

    def __init__(self, paid_hook=None):
        # Hook(event) runs after commit, outside a DB transaction. It must
        # deduplicate by event_id: crash recovery provides at-least-once delivery.
        self.paid_hook = paid_hook

    @staticmethod
    def _clean_session():
        if db.session.new or db.session.dirty or db.session.deleted:
            raise RuntimeError("Payment orchestration requires no pending unrelated writes")

    @staticmethod
    def _locked(payment_id):
        order_id = db.session.scalar(select(Payment.order_id).where(
            Payment.id == payment_id, Payment.is_deleted.is_(False),
        ))
        if order_id is None:
            raise ResourceNotFoundException("Payment not found")
        # Every financial operation uses order -> payment -> invoice lock order.
        # Financial evidence must remain processable after terminal-order soft
        # deletion, especially late approval for a cancelled order.
        order = db.session.scalar(select(Order).where(Order.id == order_id)
            .with_for_update().execution_options(populate_existing=True))
        payment = db.session.scalar(select(Payment).where(Payment.id == payment_id,
            Payment.is_deleted.is_(False)).with_for_update().execution_options(populate_existing=True))
        invoice = db.session.scalar(select(Invoice).where(Invoice.order_id == order_id,
            Invoice.is_deleted.is_(False)).with_for_update().execution_options(populate_existing=True))
        if order is None or payment is None or invoice is None:
            raise BadRequestException("Incomplete order payment records")
        return order, payment, invoice

    def claim(self, payment_id, operation, customer_id=None):
        self._clean_session()
        try:
            order, payment, invoice = self._locked(payment_id)
            if order.is_deleted and operation != "verify":
                raise BadRequestException("Deleted orders cannot start payment operations")
            if payment.payment_method != "ONLINE" or payment.currency != "USD":
                raise BadRequestException("Only ONLINE USD payments are supported")
            if (payment.amount != order.total_amount or payment.amount != invoice.total_amount
                    or invoice.currency != payment.currency or order.currency != payment.currency
                    or order.payment_status != payment.payment_status
                    or invoice.payment_status != payment.payment_status):
                raise BadRequestException("Inconsistent financial records")
            if operation == "cancel":
                if type(customer_id) is not int or customer_id != order.customer_id:
                    raise BadRequestException("Customer does not own this order")
                if order.order_status == "CANCELLED":
                    db.session.rollback()
                    return None
                if order.order_status != "PENDING":
                    raise BadRequestException("Only PENDING orders may be cancelled")
            if payment.payment_status == "PAID":
                db.session.rollback()
                return None
            if payment.payment_status not in ("PENDING", "CANCELLED"):
                raise BadRequestException("Payment requires manual review")
            now = DateUtil.now()
            if payment.gateway_lease_until and payment.gateway_lease_until > now:
                raise BadRequestException("Payment operation is already in progress")
            if operation == "initialize":
                if order.order_status != "PENDING" or payment.payment_status != "PENDING":
                    raise BadRequestException("Order cannot initialize payment")
                if payment.transaction_id:
                    raise BadRequestException("Payment already attempted; verify the existing transaction")
                if payment.amount < Decimal("0.01"):
                    raise BadRequestException("PayWay requires at least 0.01 USD")
                payment.transaction_id = uuid4().hex[:20]
            elif not payment.transaction_id:
                raise BadRequestException("Payment has no gateway transaction to verify")
            if operation == "cancel":
                # Step 4 creates one attempt. Multiple attempts require closing
                # every attempt; never infer safety from only one payment.
                ids = db.session.scalars(select(Payment.id).where(Payment.order_id == order.id)).all()
                if ids != [payment.id]:
                    raise BadRequestException("Multiple payment attempts require manual review")
            token = uuid4().hex
            payment.gateway_lease_token = token
            payment.gateway_lease_until = now + timedelta(seconds=current_app.config.get("PAYWAY_LEASE_SECONDS", 90))
            payment.gateway_state = "INITIALIZING" if operation == "initialize" else "VERIFYING"
            payment.next_check_at = payment.gateway_lease_until
            context = PaymentContext(payment.id, order.id, payment.transaction_id,
                current_app.config["PAYWAY_MERCHANT_ID"], payment.amount, payment.currency, token)
            db.session.commit()
            return context
        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _evidence(context, result):
        if (not isinstance(result, GatewayResult) or result.transaction_id != context.transaction_id
                or result.merchant_id != context.merchant_id or result.currency != context.currency
                or not isinstance(result.amount, Decimal) or not result.amount.is_finite()
                or result.amount != context.amount):
            raise GatewayError("Gateway evidence does not match payment")

    def apply(self, context, result, operation, reason=None, actor_id=None):
        self._clean_session()
        try:
            self._evidence(context, result)
            order, payment, invoice = self._locked(context.payment_id)
            if (payment.gateway_lease_token != context.lease_token
                    or payment.gateway_lease_until is None
                    or payment.gateway_lease_until <= DateUtil.now()):
                raise BadRequestException("Stale gateway operation; reconciliation required")
            if (payment.transaction_id != context.transaction_id or payment.amount != context.amount
                    or payment.currency != context.currency or order.total_amount != payment.amount
                    or invoice.total_amount != payment.amount
                    or order.currency != payment.currency or invoice.currency != payment.currency
                    or order.payment_status != payment.payment_status
                    or invoice.payment_status != payment.payment_status):
                raise BadRequestException("Payment changed during gateway operation")
            now = DateUtil.now()
            if result.status == "APPROVED":
                if not result.reference:
                    raise GatewayError("Missing verified approval reference")
                payment.payment_status = order.payment_status = invoice.payment_status = "PAID"
                payment.paid_at = payment.paid_at or now
                invoice.paid_at = invoice.paid_at or now
                payment.payment_reference = result.reference
                if order.order_status == "CANCELLED":
                    payment.gateway_state = "REFUND_REVIEW_NOTIFY_PENDING"
                    payment.checkout_message = "Payment received after cancellation; refund review required"
                else:
                    payment.gateway_state = "PAID_NOTIFY_PENDING"
                    payment.checkout_message = "Payment verified"
                payment.next_check_at = None
            elif result.status == "READY" and operation == "initialize":
                if order.order_status != "PENDING" or payment.payment_status != "PENDING":
                    raise BadRequestException("Order no longer accepts payment initialization")
                payment.qr_string = result.qr_string
                payment.abapay_deeplink = result.abapay_deeplink
                payment.expires_at = result.expires_at
                payment.gateway_state = "READY"
                payment.checkout_message = "Awaiting payment"
                payment.next_check_at = now + timedelta(seconds=30)
            elif result.status == "CLOSED" and operation == "cancel":
                if order.order_status != "PENDING" or payment.payment_status != "PENDING":
                    raise BadRequestException("Order cannot release inventory")
                ids = db.session.scalars(select(Payment.id).where(Payment.order_id == order.id)).all()
                if ids != [payment.id]:
                    raise BadRequestException("Multiple payment attempts require manual review")
                # Include original snapshots even if an item was soft-deleted:
                # checkout deducted every item's quantity.
                items = db.session.scalars(select(OrderItem).where(OrderItem.order_id == order.id)).all()
                quantities = {}
                for item in items:
                    quantities[item.variant_stock_id] = quantities.get(item.variant_stock_id, 0) + item.quantity
                VariantStockService().change_order_stock(quantities, True, order.id,
                    order.order_code, commit=False, user_id=actor_id or order.customer_id)
                order.order_status = "CANCELLED"
                order.cancelled_at = now
                payment.payment_status = order.payment_status = invoice.payment_status = "CANCELLED"
                payment.gateway_state = "CLOSED"
                payment.cancellation_reason = reason
                payment.checkout_message = "Gateway transaction closed; order cancelled"
                payment.next_check_at = None
                db.session.add(OrderStatusHistory(order_id=order.id, old_status="PENDING",
                    new_status="CANCELLED", note=reason, changed_at=now,
                    changed_by=actor_id or order.customer_id, create_uid=actor_id or order.customer_id))
            elif result.status in ("PENDING", "CANCELLED", "DECLINED"):
                # Only an explicit successful Close Transaction may release
                # inventory. Neither QR expiry nor a failed check does so.
                payment.gateway_state = "RECONCILE_REQUIRED"
                payment.checkout_message = "Payment requires reconciliation"
                payment.next_check_at = now + timedelta(seconds=30)
            else:
                raise GatewayError("Unexpected gateway operation result")
            payment.gateway_lease_token = None
            payment.gateway_lease_until = None
            payment.updated_at = order.updated_at = invoice.updated_at = now
            response = PaymentResponseSchema().dump(payment)
            if result.qr_image is not None:
                response["qr_image"] = result.qr_image  # Never persisted.
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        if result.status == "APPROVED":
            self.dispatch_paid_notification(context.payment_id)
        return response

    def mark_uncertain(self, context):
        """A transport/protocol failure is not evidence of nonpayment."""
        self._clean_session()
        try:
            _, payment, _ = self._locked(context.payment_id)
            if payment.gateway_lease_token == context.lease_token:
                payment.gateway_state = "RECONCILE_REQUIRED"
                payment.checkout_message = "Payment status unavailable; verification required"
                payment.next_check_at = DateUtil.now() + timedelta(seconds=30)
                payment.gateway_lease_token = None
                payment.gateway_lease_until = None
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    def defer_reconciliation(self, payment_id, manual_review=False):
        """Back off an unprocessable due row without changing financial state."""
        self._clean_session()
        try:
            payment = db.session.scalar(select(Payment).where(
                Payment.id == payment_id, Payment.is_deleted.is_(False)
            ).with_for_update().execution_options(populate_existing=True))
            now = DateUtil.now()
            if (payment is not None and payment.payment_status == "PENDING"
                    and payment.payment_method == "ONLINE"
                    and payment.next_check_at is not None and payment.next_check_at <= now
                    and (payment.gateway_lease_until is None or payment.gateway_lease_until <= now)):
                payment.next_check_at = None if manual_review else now + timedelta(minutes=5)
                payment.checkout_message = ("Manual review required: outside automated check window"
                    if manual_review else "Reconciliation deferred; review unresolved payment if persistent")
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise

    def response(self, payment_id):
        self._clean_session()
        try:
            payment = db.session.scalar(select(Payment).where(Payment.id == payment_id, Payment.is_deleted.is_(False)))
            if payment is None:
                raise ResourceNotFoundException("Payment not found")
            return PaymentResponseSchema().dump(payment)
        finally:
            db.session.rollback()  # End the read transaction before returning.

    def dispatch_paid_notification(self, payment_id):
        """Durable pending/ack markers; external delivery is at-least-once."""
        if self.paid_hook is None:
            return False
        self._clean_session()
        token = None
        try:
            order, payment, _ = self._locked(payment_id)
            now = DateUtil.now()
            if (payment.gateway_state not in self.NOTIFICATION_STATES
                    or payment.payment_status != "PAID"
                    or payment.gateway_lease_until and payment.gateway_lease_until > now):
                db.session.rollback()
                return False
            token = uuid4().hex
            payment.gateway_lease_token = token
            payment.gateway_lease_until = now + timedelta(seconds=90)
            review = payment.gateway_state == "REFUND_REVIEW_NOTIFY_PENDING"
            event = {"event_id": f"payment:{payment.id}:paid", "payment_id": payment.id,
                     "order_id": order.id, "refund_review": review}
            db.session.commit()
            # No open transaction or locks across the external hook.
            self.paid_hook(event)
            _, payment, _ = self._locked(payment_id)
            if payment.gateway_lease_token == token:
                payment.gateway_state = "REFUND_REVIEW" if review else "PAID"
                payment.gateway_lease_token = payment.gateway_lease_until = None
            db.session.commit()
            return True
        except Exception as error:
            db.session.rollback()
            from app.services.notifications.telegram_notification_service import NotificationDeliveryError
            if token and isinstance(error, NotificationDeliveryError):
                try:
                    _, payment, _ = self._locked(payment_id)
                    if payment.gateway_lease_token == token:
                        payment.gateway_lease_until = DateUtil.now() + timedelta(seconds=error.retry_after)
                    db.session.commit()
                except Exception:
                    db.session.rollback()
            # The marker remains durable, and the lease expires for retry.
            logger.error("Payment notification hook deferred; retry required")
            return False

    def dispatch_pending_notifications(self, limit=100):
        self._clean_session()
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("Invalid notification batch size")
        try:
            ids = db.session.scalars(select(Payment.id).where(
                Payment.is_deleted.is_(False), Payment.payment_status == "PAID",
                Payment.gateway_state.in_(self.NOTIFICATION_STATES),
                (Payment.gateway_lease_until.is_(None)) | (Payment.gateway_lease_until <= DateUtil.now()),
            ).order_by(Payment.id).limit(limit)).all()
        finally:
            db.session.rollback()
        return sum(self.dispatch_paid_notification(id) for id in ids)
