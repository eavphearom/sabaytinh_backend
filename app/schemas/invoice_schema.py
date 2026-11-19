from marshmallow import fields
from app.schemas.order_schema import InvoiceResponseSchema, OrderItemResponseSchema, EnumValueField


class CustomerInvoiceSchema(InvoiceResponseSchema):
    order_code = fields.String()
    order_status = EnumValueField()
    recipient_name = fields.String()
    recipient_phone = fields.String()
    delivery_address = fields.String()
    delivery_method_name = fields.String()
    items = fields.List(fields.Nested(OrderItemResponseSchema))
