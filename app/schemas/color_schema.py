
from marshmallow import Schema, fields, validate, RAISE


class ColorRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=100)
    )

    hex_code = fields.String(
        allow_none=True,
        validate=validate.Length(max=50)
    )

    is_active = fields.Boolean(load_default=True)


class ColorUpdateSchema(ColorRequestSchema):
    # Avoid changing is_active when omitted.
    is_active = fields.Boolean()


class ColorResponseSchema(Schema):
    id = fields.Integer()
    name = fields.String()
    hex_code = fields.String(allow_none=True)
    is_active = fields.Boolean()
    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )
