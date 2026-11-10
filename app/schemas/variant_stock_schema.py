from marshmallow import Schema, fields, validate, RAISE
class VariantStockRequestSchema(Schema):
    class Meta: unknown = RAISE
    variant_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))
    size_id = fields.Integer(required=True, strict=True, validate=validate.Range(min=1))
    sku = fields.String(required=True, validate=validate.Length(min=1,max=100))
    low_stock_alert = fields.Integer(load_default=0, strict=True, validate=validate.Range(min=0))
class VariantStockUpdateSchema(Schema):
    class Meta: unknown = RAISE
    sku = fields.String(validate=validate.Length(min=1,max=100))
    low_stock_alert = fields.Integer(strict=True, validate=validate.Range(min=0))
class StockSetSchema(Schema):
    class Meta: unknown = RAISE
    target_qty = fields.Integer(required=True, strict=True, validate=validate.Range(min=0,max=2147483647))
    note = fields.String(allow_none=True, validate=validate.Length(max=500))
class StockChangeSchema(Schema):
    class Meta: unknown = RAISE
    quantity = fields.Integer(required=True, strict=True, validate=validate.Range(min=1,max=2147483647))
    unit_id = fields.Integer(strict=True, validate=validate.Range(min=1))
    reference_type = fields.String(validate=validate.OneOf(["MANUAL_ADJUSTMENT","ORDER","ORDER_RETURN"]))
    reference_id = fields.Integer(allow_none=True, strict=True, validate=validate.Range(min=1))
    note = fields.String(allow_none=True, validate=validate.Length(max=500))
class VariantStockResponseSchema(Schema):
    id = fields.Integer()
    variant_id = fields.Integer()
    size_id = fields.Integer()
    unit_id = fields.Integer()
    sku = fields.String()
    qty = fields.Integer()
    low_stock_alert = fields.Integer()
    created_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True)
    updated_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True)
