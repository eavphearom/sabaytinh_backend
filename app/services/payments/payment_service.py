import logging
from datetime import timedelta

from sqlalchemy import select

from app.exceptions.api_exception import BadRequestException
from app.extensions import db
from app.models import Payment
from app.repositories.payment_repository import PaymentRepository
from app.services.payments.payment_strategy import GatewayError
from app.services.payments.payment_strategy_factory import PaymentStrategyFactory
from app.services.payments.payment_state_service import PaymentStateService
from app.utils.date_util import DateUtil


class PaymentService:
    def __init__(self, paid_hook=None):
        if paid_hook is None:
            from app.services.notifications.telegram_notification_service import TelegramNotificationService
            paid_hook = TelegramNotificationService().notify_verified_payment
        self.state = PaymentStateService(paid_hook=paid_hook)

    def _run(self, payment_id, operation, customer_id=None, reason=None, actor_id=None):
        # Validate gateway configuration before touching financial state.
        strategy = PaymentStrategyFactory.resolve("ONLINE")
        context = self.state.claim(payment_id, operation, customer_id)
        if context is None:
            return self.state.response(payment_id)
        try:
            if db.session().in_transaction():
                raise RuntimeError("Gateway I/O must not run inside a DB transaction")
            if operation == "initialize":
                result = strategy.initialize(context)
            else:
                result = strategy.verify(context)
                self.state._evidence(context, result)
                if operation == "cancel" and result.status != "APPROVED":
                    result = strategy.close(context)
            return self.state.apply(context, result, operation, reason, actor_id=actor_id)
        except Exception:
            # Preserve transaction ID on uncertain initialization: never retry
            # creation with a fresh ID and risk charging the same order twice.
            self.state.mark_uncertain(context)
            raise

    def initialize(self, payment_id):
        """Call only after CheckoutService has committed."""
        return self._run(payment_id, "initialize")

    def verify(self, payment_id):
        return self._run(payment_id, "verify")

    def cancel(self, payment_id, authenticated_customer_id, reason, *, actor_id=None):
        if not isinstance(reason, str) or not reason.strip() or len(reason) > 255:
            raise BadRequestException("A cancellation reason of 1-255 characters is required")
        return self._run(payment_id, "cancel", authenticated_customer_id, reason, actor_id)

    def callback_hint(self, transaction_id):
        """A callback is an untrusted hint; only server-to-server checks can pay.

        The HTTP route authenticates its HMAC, limits input and rate-limits
        hints. Never pass callback status to apply, even after authentication.
        """
        self.state._clean_session()
        if not isinstance(transaction_id, str) or not 1 <= len(transaction_id) <= 20:
            raise BadRequestException("Invalid transaction ID")
        try:
            payment_id = db.session.scalar(select(Payment.id).where(
                Payment.transaction_id == transaction_id, Payment.is_deleted.is_(False),
            ))
        finally:
            db.session.rollback()
        if payment_id is None:
            raise BadRequestException("Unknown payment transaction")
        return self.verify(payment_id)

    def reconcile_due(self, limit=100, should_stop=None):
        """Internal scheduler entry point. QR expiry alone never cancels an order."""
        self.state._clean_session()
        try:
            records = [(p.id, p.created_at) for p in PaymentRepository().find_pending_online_for_reconciliation(
                DateUtil.now(), limit=limit, for_update=False)]
        finally:
            db.session.rollback()
        results = {}
        for id, created_at in records:
            if should_stop and should_stop():
                break
            try:
                if created_at <= DateUtil.now() - timedelta(days=7):
                    self.state.defer_reconciliation(id, manual_review=True)
                    results[id] = {"manual_review_required": True}
                    continue
                results[id] = self.verify(id)
            except Exception:
                db.session.rollback()
                # Isolate broken records so they cannot starve the remaining
                # batch. Existing gateway errors already schedule a short retry.
                try:
                    self.state.defer_reconciliation(id)
                except Exception:
                    db.session.rollback()
                logging.getLogger(__name__).warning("Payment reconciliation deferred payment_id=%s", id)
                results[id] = {"verification_pending": True}
        return results
