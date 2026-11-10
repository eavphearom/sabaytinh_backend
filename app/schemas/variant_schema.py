from decimal import Decimal
from marshmallow import Schema, fields, validate, RAISE
class VariantRequestSchema(Schema):
    class Meta: unknown = RAISE
    product_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))
    color_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))
    sku_prefix = fields.String(required=True, validate=validate.Length(min=1, max=100))
    cost = fields.Decimal(as_string=True, load_default=Decimal("0"), validate=validate.Range(min=0))
    price = fields.Decimal(as_string=True, load_default=Decimal("0"), validate=validate.Range(min=0))
    is_default = fields.Boolean(load_default=False)
    is_active = fields.Boolean(load_default=True)
class VariantUpdateSchema(Schema):
    class Meta: unknown = RAISE
    color_id = fields.Integer(strict=True, validate=validate.Range(min=1))
    sku_prefix = fields.String(validate=validate.Length(min=1, max=100))
    cost = fields.Decimal(as_string=True, validate=validate.Range(min=0))
    price = fields.Decimal(as_string=True, validate=validate.Range(min=0))
    is_default = fields.Boolean()
    is_active = fields.Boolean()
class VariantResponseSchema(Schema):
    id = fields.Integer()
    product_id = fields.Integer()
    color_id = fields.Integer()
    sku_prefix = fields.String()
    cost = fields.Decimal(as_string=True)
    price = fields.Decimal(as_string=True)
    is_default = fields.Boolean()
    is_active = fields.Boolean()
    created_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True)
    updated_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True)
