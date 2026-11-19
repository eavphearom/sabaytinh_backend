from app.common.base_repository import BaseRepository
from app.extensions import db
from app.models.invoice import Invoice
from app.models.order import Order
from app.models.order_item import OrderItem
from sqlalchemy import select
from sqlalchemy.orm import joinedload, selectinload


class InvoiceRepository(BaseRepository):
    def __init__(self):
        super().__init__(Invoice)

    def find_by_order_id(self, order_id):
        return db.session.scalar(self._query().where(Invoice.order_id == order_id))

    def find_by_invoice_no(self, invoice_no):
        return db.session.scalar(self._query().where(Invoice.invoice_no == invoice_no))

    def find_customer_invoice(self, order_id, customer_id):
        return db.session.scalar(select(Invoice).join(Order, Invoice.order_id == Order.id).where(
            Invoice.order_id == order_id, Order.customer_id == customer_id,
            Invoice.is_deleted.is_(False), Order.is_deleted.is_(False),
        ).options(joinedload(Invoice.order).selectinload(
            Order.items.and_(OrderItem.is_deleted.is_(False))
        )).execution_options(populate_existing=True))

    def save(self, invoice):
        """Insert or flush a service-modified entity without ending its transaction."""
        db.session.add(invoice)
        db.session.flush()
        return invoice

    create = save
    update = save
