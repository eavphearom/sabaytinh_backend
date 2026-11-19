from app.repositories.invoice_repository import InvoiceRepository
from app.schemas.invoice_schema import CustomerInvoiceSchema
from app.schemas.order_schema import InvoiceResponseSchema
from app.exceptions.api_exception import ResourceNotFoundException


class InvoiceService:
    def get_customer_invoice(self, order_id, customer_id):
        if type(order_id) is not int or not 1 <= order_id <= 9_223_372_036_854_775_807:
            raise ResourceNotFoundException("Invoice not found")
        invoice = InvoiceRepository().find_customer_invoice(order_id, customer_id)
        if invoice is None:
            raise ResourceNotFoundException("Invoice not found")
        order = invoice.order
        # Money and payment status come from the persisted invoice; never recalculate
        # using current catalog prices or infer payment from an order's status.
        data = {key: getattr(invoice, key) for key in InvoiceResponseSchema().fields}
        for key in ("order_code", "order_status", "recipient_name", "recipient_phone",
                    "delivery_address", "delivery_method_name"):
            data[key] = getattr(order, key)
        data["items"] = sorted(order.items, key=lambda item: item.id)
        return CustomerInvoiceSchema().dump(data)
