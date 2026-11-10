
from decimal import Decimal

from marshmallow import Schema, fields, validate, RAISE


class ProductUnitRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    unit_id = fields.Integer(
        required=True,
        strict=True,
        validate=validate.Range(min=1)
    )

    multiplier = fields.Decimal(
        as_string=True,
        load_default=Decimal("1.00000"),
        validate=validate.Range(min=Decimal("0.00001"))
    )


class ProductUnitUpdateSchema(Schema):
    class Meta:
        unknown = RAISE

    multiplier = fields.Decimal(
        as_string=True,
        required=True,
        validate=validate.Range(min=Decimal("0.00001"))
    )


class ProductUnitResponseSchema(Schema):
    id = fields.Integer()
    product_id = fields.Integer()
    unit_id = fields.Integer()
    multiplier = fields.Decimal(as_string=True)

    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )
