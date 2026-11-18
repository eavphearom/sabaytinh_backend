
from marshmallow import Schema, fields

from app.schemas.order_schema import EnumValueField, ImageURLField


class WebAccountOverviewSchema(Schema):
    total_orders = fields.Integer(data_key="totalOrders")
    in_progress = fields.Integer(data_key="inProgress")
    completed = fields.Integer()


class WebAccountPreviewSchema(Schema):
    product_name = fields.String()
    image = ImageURLField(allow_none=True)
    color = fields.String(attribute="color_name", allow_none=True)
    size = fields.String(attribute="size_name", allow_none=True)
    qty = fields.Integer(attribute="quantity")
    price = fields.Float(attribute="unit_price")


class WebAccountOrderSchema(Schema):
    id = fields.Integer()
    order_code = fields.String()
    created_at = fields.DateTime(
        format="%Y-%m-%dT%H:%M:%S",
        allow_none=True
    )
    total = fields.Float()
    order_status = EnumValueField()
    payment_status = EnumValueField()
    total_items = fields.Integer()
    preview_item = fields.Nested(
        WebAccountPreviewSchema,
        allow_none=True
    )
