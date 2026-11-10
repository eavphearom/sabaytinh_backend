from decimal import Decimal

from marshmallow import (
    Schema,
    fields,
    RAISE,
    ValidationError,
    validates_schema,
    validate,
)
from app.enums.currency import Currency
from app.utils.file_util import FileUtil


class DeliveryMethodRequestSchema(Schema):

    class Meta:
        unknown = RAISE

    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=120)
    )

    fee = fields.Decimal(
        required=True,
        places=5,
        as_string=True
    )

    currency = fields.String(
        load_default=Currency.USD.value,
        validate=validate.OneOf(
            [currency.value for currency in Currency]
        )
    )

    estimated_min_days = fields.Integer(
        allow_none=True,
        load_default=None
    )

    estimated_max_days = fields.Integer(
        allow_none=True,
        load_default=None
    )

    is_active = fields.Boolean(
        load_default=True
    )

    @validates_schema
    def validate_fields(self, data, **kwargs):
        if not data.get("name", "").strip():
            raise ValidationError(
                "Name is required",
                field_name="name"
            )

        fee = data.get("fee")

        if fee is not None and (
            not fee.is_finite()
            or fee < 0
            or fee > Decimal("99999.99999")
        ):
            raise ValidationError(
                "Fee must be between 0 and 99999.99999",
                field_name="fee"
            )

        minimum = data.get("estimated_min_days")
        maximum = data.get("estimated_max_days")

        if minimum is not None and minimum < 0:
            raise ValidationError(
                "Minimum days cannot be negative",
                field_name="estimated_min_days"
            )

        if maximum is not None and maximum < 0:
            raise ValidationError(
                "Maximum days cannot be negative",
                field_name="estimated_max_days"
            )

        if (
            minimum is not None
            and maximum is not None
            and minimum > maximum
        ):
            raise ValidationError(
                "Minimum days cannot exceed maximum days"
            )


class DeliveryMethodResponseSchema(Schema):

    id = fields.Integer()
    name = fields.String()
    code = fields.String()

    fee = fields.Decimal(
        as_string=True,
        places=5
    )

    currency = fields.String()

    estimated_min_days = fields.Integer(
        allow_none=True
    )

    estimated_max_days = fields.Integer(
        allow_none=True
    )

    logo = fields.Method("logo_url")

    is_active = fields.Boolean()

    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    def logo_url(self, obj):
        return (
            FileUtil.get_image_url(obj.logo)
            if obj.logo else None
        )