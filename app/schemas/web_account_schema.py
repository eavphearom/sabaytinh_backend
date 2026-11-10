from marshmallow import Schema, fields

from app.schemas.order_schema import EnumValueField, ImageURLField


class WebAccountOverviewSchema(Schema):
    total_orders = fields.Integer(data_key="totalOrders")
    in_progress = fields.Integer(data_key="inProgress")
    completed = fields.Integer()


class WebAccountPreviewSchema(Schema):
    product_name = fields.String(data_key="productName")
    image = ImageURLField(allow_none=True)
    color_name = fields.String(data_key="colorName", allow_none=True)
    size_name = fields.String(data_key="sizeName", allow_none=True)
    quantity = fields.Integer()
    unit_price = fields.Float(data_key="unitPrice")


class WebAccountOrderSchema(Schema):
    id = fields.Integer()
    order_code = fields.String(data_key="orderCode")
    created_at = fields.DateTime(data_key="createdAt", format="%Y-%m-%dT%H:%M:%S", allow_none=True)
    total = fields.Float()
    order_status = EnumValueField(data_key="orderStatus")
    payment_status = EnumValueField(data_key="paymentStatus")
    total_items = fields.Integer(data_key="totalItems")
    preview_item = fields.Nested(WebAccountPreviewSchema, data_key="previewItem", allow_none=True)
