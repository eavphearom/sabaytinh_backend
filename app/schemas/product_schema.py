
from marshmallow import (
    Schema,
    fields,
    validate,
    validates_schema,
    ValidationError,
    RAISE,
)
from decimal import Decimal


class VariantImageRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    id = fields.Integer(
        validate=validate.Range(min=1)
    )
    is_primary = fields.Boolean(load_default=False)

    # Uploaded image files are handled by ProductRequestMapper.


class VariantStockRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    id = fields.Integer(
        validate=validate.Range(min=1)
    )

    size_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1)
    )

    qty = fields.Integer(
        allow_none=True,
        validate=validate.Range(min=0)
    )

    low_stock_alert = fields.Integer(
        load_default=0,
        validate=validate.Range(min=0)
    )


class VariantRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    id = fields.Integer(
        validate=validate.Range(min=1)
    )

    color_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1)
    )

    cost = fields.Decimal(
        as_string=True,
        load_default=Decimal("0"),
        validate=validate.Range(min=0)
    )

    price = fields.Decimal(
        required=True,
        as_string=True,
        validate=validate.Range(min=0)
    )

    is_default = fields.Boolean(load_default=False)
    is_active = fields.Boolean(load_default=True)

    images = fields.List(
        fields.Nested(VariantImageRequestSchema),
        load_default=list
    )

    stocks = fields.List(
        fields.Nested(VariantStockRequestSchema),
        required=True,
        validate=validate.Length(min=1)
    )

    @validates_schema
    def validate_stocks(self, data, **kwargs):
        size_ids = [
            stock["size_id"]
            for stock in data.get("stocks", [])
        ]

        if len(size_ids) != len(set(size_ids)):
            raise ValidationError(
                "Duplicate sizes within a variant"
            )


class ProductRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    category_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1)
    )

    brand_id = fields.Integer(
        required=True,
        validate=validate.Range(min=1)
    )

    # Optional for compatibility; service generates code.
    code = fields.String(
        validate=validate.Length(max=100),
        allow_none=True
    )

    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=150)
    )

    description = fields.String(allow_none=True)
    is_active = fields.Boolean(load_default=True)

    variants = fields.List(
        fields.Nested(VariantRequestSchema),
        required=True,
        validate=validate.Length(min=1)
    )

    @validates_schema
    def validate_variants(self, data, **kwargs):
        variants = data.get("variants", [])

        colors = [v["color_id"] for v in variants]

        if len(colors) != len(set(colors)):
            raise ValidationError(
                "Each variant must have a unique color"
            )

        default_count = sum(
            v.get("is_default", False) for v in variants
        )

        if default_count != 1:
            raise ValidationError(
                "Exactly one default variant is required"
            )


class ProductUpdateSchema(ProductRequestSchema):
    pass


class ProductResponseSchema(Schema):
    id = fields.Integer()
    category_id = fields.Integer()
    brand_id = fields.Integer()
    unit_id = fields.Integer()
    code = fields.String()
    name = fields.String()
    slug = fields.String()
    description = fields.String(allow_none=True)
    is_active = fields.Boolean()

    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    # Nested response mapping will be added in ProductService.


class ProductPaginationResponseSchema(Schema):
    id = fields.Integer()
    code = fields.String()
    name = fields.String()
    image = fields.Method("image_url")
    created_at = fields.DateTime(format="%Y-%m-%dT%H:%M:%S", allow_none=True)
    category_id = fields.Integer()
    category_name = fields.String(allow_none=True)
    brand_id = fields.Integer()
    brand_name = fields.String(allow_none=True)
    total_variants = fields.Integer()
    min_price = fields.Float(allow_none=True)
    max_price = fields.Float(allow_none=True)
    total_stock = fields.Integer()
    is_active = fields.Boolean()

    def image_url(self, obj):
        from app.utils.file_util import FileUtil
        return FileUtil.get_image_url(obj["image"])
