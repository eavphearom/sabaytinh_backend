from app.common.base_repository import BaseRepository
from app.extensions import db
from app.models.invoice import Invoice


class InvoiceRepository(BaseRepository):
    def __init__(self):
        super().__init__(Invoice)

    def find_by_order_id(self, order_id):
        return db.session.scalar(self._query().where(Invoice.order_id == order_id))

    def find_by_invoice_no(self, invoice_no):
        return db.session.scalar(self._query().where(Invoice.invoice_no == invoice_no))

    def save(self, invoice):
        """Insert or flush a service-modified entity without ending its transaction."""
        db.session.add(invoice)
        db.session.flush()
        return invoice

    create = save
    update = save
