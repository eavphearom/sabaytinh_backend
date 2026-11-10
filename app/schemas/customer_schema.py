from marshmallow import Schema, fields
from app.schemas.order_schema import ImageURLField


class CustomerListSchema(Schema):
    id = fields.Integer()
    username = fields.String()
    email = fields.String()
    total_orders = fields.Integer(data_key="totalOrders")
    total_spent = fields.Decimal(places=2, as_string=True, allow_none=True, data_key="totalSpent")
    last_order_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", data_key="lastOrderAt")
    currency = fields.String(allow_none=True)
    total_spent_by_currency = fields.Dict(keys=fields.String(),
        values=fields.Decimal(places=2, as_string=True), data_key="totalSpentByCurrency")


class CustomerDetailSchema(CustomerListSchema):
    phone = fields.String(allow_none=True)
    profile = ImageURLField(allow_none=True)
    status = fields.String()
    created_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True, data_key="createdAt")
