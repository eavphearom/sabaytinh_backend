from sqlalchemy import select

from app.exceptions.api_exception import BadRequestException, ResourceNotFoundException
from app.extensions import db
from app.models import Order, Payment, Invoice, OrderStatusHistory
from app.repositories.order_repository import OrderRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.order_status_history_repository import OrderStatusHistoryRepository
from app.schemas.order_schema import (
    OrderResponseSchema, OrderPaginationResponseSchema, OrderHistoryResponseSchema,
    AccountOverviewResponseSchema, CheckoutRequestSchema,
)
from app.services.checkout_service import CheckoutService
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_strategy import GatewayError
from app.services.payments.public_payment_gate import require_public_payment_ready
from app.utils.date_util import DateUtil


class OrderService:
    FORWARD = {"PENDING": 0, "PROCESSING": 1, "SHIPPED": 2, "DELIVERED": 3}

    def __init__(self):
        self.orders = OrderRepository()

    @staticmethod
    def _validate_id(order_id):
        if type(order_id) is not int or not 1 <= order_id <= 9_223_372_036_854_775_807:
            raise ResourceNotFoundException("Order not found")

    def _get(self, order_id, customer_id=None):
        self._validate_id(order_id)
        order = (self.orders.find_by_id(order_id) if customer_id is None else
                 self.orders.find_by_id_and_customer_id(order_id, customer_id))
        if order is None:
            raise ResourceNotFoundException("Order not found")
        return order

    def get_detail(self, order_id, customer_id=None):
        order = self._get(order_id, customer_id)
        data = OrderResponseSchema().dump(order)
        data["items"].sort(key=lambda item: item["id"])
        data["payments"].sort(key=lambda item: item["id"])
        data["status_history"].sort(key=lambda item: (item["changed_at"], item["id"]))
        return data

    def get_paginated(self, filters, params):
        result = self.orders.find_paginated(filters, params)
        rows = []
        for order in result["items"]:
            data = OrderPaginationResponseSchema().dump(order)
            latest = max(order.payments, key=lambda p: (p.created_at, p.id), default=None)
            data.update(customer_name=order.customer.username if order.customer else None,
                        payment_method=latest.payment_method.value if latest else None,
                        total_items=sum(item.quantity for item in order.items))
            rows.append(data)
        return {**result, "items": rows}

    def get_customer_history(self, customer_id, filters, params):
        result = self.orders.find_customer_history(customer_id, filters, params)
        rows = []
        for order in result["items"]:
            item = min(order.items, key=lambda item: item.id, default=None)
            rows.append(OrderHistoryResponseSchema().dump({
                "id": order.id, "order_code": order.order_code, "created_at": order.created_at,
                "total": order.total_amount, "order_status": order.order_status,
                "payment_status": order.payment_status, "total_items": sum(i.quantity for i in order.items),
                "preview_item": {"product_name": item.product_name, "image": item.image,
                    "color": item.color_name, "size": item.size_name,
                    "qty": item.quantity, "price": item.unit_price} if item else None,
            }))
        return {**result, "items": rows}

    def get_account_overview(self, customer_id):
        return AccountOverviewResponseSchema().dump(self.orders.get_account_overview(customer_id))

    def checkout(self, customer_id, payload):
        # Must precede CheckoutService: disabled checkout cannot deduct stock.
        require_public_payment_ready()
        data = CheckoutRequestSchema().load(payload)
        result = CheckoutService().checkout(customer_id, data)
        try:
            payment = PaymentService().initialize(result["payment_id"])
        except (GatewayError, BadRequestException):
            # Checkout has committed. Return the existing order, not an opaque
            # error that encourages the customer to submit a second checkout.
            return self.get_detail(result["order_id"], customer_id), False
        order = self.get_detail(result["order_id"], customer_id)
        order["payments"] = [payment if p["id"] == payment["id"] else p for p in order["payments"]]
        return order, True

    def _payment_for(self, order_id, customer_id=None):
        order = self._get(order_id, customer_id)
        payments = PaymentRepository().find_by_order_id(order.id)
        if len(payments) != 1:
            raise BadRequestException("Order requires payment review")
        return order, payments[0].id

    def check_payment(self, order_id, customer_id):
        _, payment_id = self._payment_for(order_id, customer_id)
        require_public_payment_ready()
        return PaymentService().verify(payment_id)

    def cancel(self, order_id, actor_id, reason, admin=False):
        order, payment_id = self._payment_for(order_id, None if admin else actor_id)
        if order.order_status == "CANCELLED":
            return self.get_detail(order_id, None if admin else actor_id)
        if order.order_status != "PENDING":
            raise BadRequestException("Only PENDING orders may be safely cancelled")
        owner_id = order.customer_id
        require_public_payment_ready()
        PaymentService().cancel(payment_id, owner_id, reason, actor_id=actor_id)
        data = self.get_detail(order_id, None if admin else actor_id)
        if data["order_status"] != "CANCELLED":
            raise BadRequestException("Verified paid orders require a refund workflow, not cancellation")
        return data

    @staticmethod
    def _financial_records(order):
        payments = db.session.scalars(select(Payment).where(Payment.order_id == order.id)
            .order_by(Payment.id).with_for_update().execution_options(populate_existing=True)).all()
        invoice = db.session.scalar(select(Invoice).where(Invoice.order_id == order.id,
            Invoice.is_deleted.is_(False)).with_for_update().execution_options(populate_existing=True))
        if len(payments) != 1 or payments[0].is_deleted or invoice is None:
            raise BadRequestException("Order requires payment review")
        return payments[0], invoice

    @staticmethod
    def _require_verified_paid(order, payment, invoice):
        if (payment.payment_method != "ONLINE" or payment.payment_status != "PAID"
                or order.payment_status != "PAID" or invoice.payment_status != "PAID"
                or payment.gateway_state not in ("PAID", "PAID_NOTIFY_PENDING")
                or not payment.transaction_id or not payment.payment_reference
                or payment.paid_at is None or invoice.paid_at is None
                or payment.amount != order.total_amount or invoice.total_amount != order.total_amount
                or payment.currency != order.currency or invoice.currency != order.currency):
            raise BadRequestException("Fulfillment requires verified ONLINE payment")

    def update_status(self, order_id, status, note, actor_id):
        self._validate_id(order_id)
        if status not in self.FORWARD:
            raise BadRequestException("Use the safe cancellation endpoint to cancel an order")
        try:
            order = self.orders.find_by_id_for_update(order_id)
            if order is None:
                raise ResourceNotFoundException("Order not found")
            old = order.order_status.value
            if old == status:
                db.session.rollback()
                return self.get_detail(order_id)
            if old in ("DELIVERED", "CANCELLED") or self.FORWARD[status] <= self.FORWARD[old]:
                raise BadRequestException("Backward or terminal status transitions are not allowed")
            payment, invoice = self._financial_records(order)
            self._require_verified_paid(order, payment, invoice)
            order.order_status = status
            order.updated_at = DateUtil.now()
            order.update_uid = actor_id
            if status == "DELIVERED":
                order.delivered_at = DateUtil.now()
            OrderStatusHistoryRepository().create(OrderStatusHistory(
                order_id=order.id, old_status=old, new_status=status, note=note,
                changed_at=DateUtil.now(), changed_by=actor_id, create_uid=actor_id,
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
        return self.get_detail(order_id)

    def manage_payment_status(self, order_id):
        self._get(order_id)
        raise BadRequestException(
            "Manual payment-status changes are disabled; use verified provider operations"
        )

    def delete(self, order_id, actor_id, reason=None):
        self._validate_id(order_id)
        if reason is not None and len(reason) > 255:
            raise BadRequestException("Deletion reason must not exceed 255 characters")
        try:
            order = self.orders.find_by_id_for_update(order_id)
            if order is None:
                raise ResourceNotFoundException("Order not found")
            if order.order_status not in ("DELIVERED", "CANCELLED"):
                raise BadRequestException("Only resolved terminal orders may be deleted")
            payment, invoice = self._financial_records(order)
            if payment.gateway_lease_token or payment.gateway_state not in ("PAID", "CLOSED"):
                raise BadRequestException("Resolve payment operations and notifications before deletion")
            if order.order_status == "DELIVERED":
                self._require_verified_paid(order, payment, invoice)
            elif (payment.payment_status != "CANCELLED" or payment.gateway_state != "CLOSED"
                  or invoice.payment_status != "CANCELLED" or order.payment_status != "CANCELLED"):
                raise BadRequestException("Cancellation payment state is unresolved")
            order.is_deleted = True
            order.deleted_at = DateUtil.now()
            order.deleted_uid = actor_id
            order.deleted_reason = reason
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
