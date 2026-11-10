from decimal import Decimal

from marshmallow import Schema, fields, validate, validates_schema, ValidationError

from app.schemas.product_schema import ProductResponseSchema
from app.utils.file_util import FileUtil


class HomeProductFilterSchema(Schema):
    type = fields.String(validate=validate.OneOf(["new"]))
    category_id = fields.Integer(validate=validate.Range(min=1, max=9223372036854775807))
    brand_id = fields.Integer(validate=validate.Range(min=1, max=9223372036854775807))
    price_sort = fields.String(validate=validate.OneOf(["asc", "desc"]))
    min_price = fields.Decimal(validate=validate.Range(min=Decimal("0"), max=Decimal("9999999999.99999")))
    max_price = fields.Decimal(validate=validate.Range(min=Decimal("0"), max=Decimal("9999999999.99999")))

    @validates_schema
    def check_combination(self, data, **kwargs):
        if data.get("min_price") is not None and data.get("max_price") is not None:
            if data["min_price"] > data["max_price"]:
                raise ValidationError("min_price must not exceed max_price")
        if data.get("type") == "new" and data.get("price_sort"):
            raise ValidationError("type=new requires newest-first ordering; omit price_sort")


class HomeProductResponseSchema(ProductResponseSchema):
    # Price is the minimum active variant price, retaining database precision.
    price = fields.Decimal(as_string=True, places=5, allow_none=True)
    image = fields.Method("image_url")

    def image_url(self, obj):
        return FileUtil.get_image_url(obj.get("image"))


class PublicVariantImageSchema(Schema):
    id = fields.Integer()
    variant_id = fields.Integer()
    image = fields.Method("image_url")
    is_primary = fields.Boolean()

    def image_url(self, obj):
        return FileUtil.get_image_url(obj.image)


class PublicVariantStockSchema(Schema):
    id = fields.Integer()
    variant_stock_id = fields.Integer()
    variant_id = fields.Integer()
    size_id = fields.Integer()
    size = fields.String(allow_none=True)
    size_name = fields.String(allow_none=True)
    unit_id = fields.Integer()
    sku = fields.String()
    qty = fields.Integer()
    stock_status = fields.String()


class PublicVariantSchema(Schema):
    id = fields.Integer()
    product_id = fields.Integer()
    color_id = fields.Integer()
    color_name = fields.String()
    color_hex = fields.String(allow_none=True)
    sku_prefix = fields.String()
    price = fields.Decimal(as_string=True, places=5)
    is_default = fields.Boolean()
    is_active = fields.Boolean()
    total_stock = fields.Integer()
    stock_status = fields.String()
    images = fields.List(fields.Nested(PublicVariantImageSchema))
    stock = fields.List(fields.Nested(PublicVariantStockSchema))


class PublicProductDetailResponseSchema(HomeProductResponseSchema):
    brand_name = fields.String(allow_none=True)
    category_name = fields.String(allow_none=True)
    variants = fields.List(fields.Nested(PublicVariantSchema))
