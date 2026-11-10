from datetime import datetime

from sqlalchemy import or_

from app.common.base_repository import BaseRepository
from app.enums.payment_method import PaymentMethod
from app.enums.payment_status import PaymentStatus
from app.extensions import db
from app.models.payment import Payment


class PaymentRepository(BaseRepository):
    def __init__(self):
        super().__init__(Payment)

    def find_by_order_id(self, order_id):
        return db.session.scalars(self._query().where(Payment.order_id == order_id)
            .order_by(Payment.created_at, Payment.id)).all()

    def find_latest_by_order_id(self, order_id):
        return db.session.scalar(self._query().where(Payment.order_id == order_id)
            .order_by(Payment.created_at.desc(), Payment.id.desc()).limit(1))

    def find_by_transaction_id(self, transaction_id, for_update=False):
        # A null callback ID must never resolve to an arbitrary pending payment.
        if not transaction_id:
            return None
        query = self._query().where(Payment.transaction_id == transaction_id)
        if for_update:
            query = query.with_for_update(of=Payment).execution_options(populate_existing=True)
        return db.session.scalar(query)

    def find_by_id_for_update(self, payment_id):
        return db.session.scalar(self._query().where(Payment.id == payment_id)
            .with_for_update(of=Payment).execution_options(populate_existing=True))

    def find_pending_online_for_reconciliation(self, now, limit=100, for_update=True):
        """Return scheduled, due rows without an active lease.

        NULL next_check_at means unscheduled. Expired payments are still returned
        so the service can reconcile their final state. The caller must retain
        the transaction and set leases before committing; this does not claim a
        durable lease or perform gateway operations.
        """
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        if not isinstance(now, datetime) or now.tzinfo is not None:
            raise ValueError("now must be a naive local datetime")
        query = self._query().where(
            Payment.payment_method == PaymentMethod.ONLINE.value,
            Payment.payment_status == PaymentStatus.PENDING.value,
            Payment.next_check_at <= now,
            or_(Payment.gateway_lease_until.is_(None), Payment.gateway_lease_until <= now),
        ).order_by(Payment.next_check_at, Payment.id).limit(limit)
        if for_update:
            query = query.with_for_update(of=Payment, skip_locked=True)
        return db.session.scalars(query.execution_options(populate_existing=True)).all()

    def save(self, payment):
        """Insert or flush a service-modified entity in the caller's transaction."""
        db.session.add(payment)
        db.session.flush()
        return payment

    create = save
    update = save
