
from marshmallow import Schema, fields, validate, RAISE


class SizeRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    name = fields.String(
        allow_none=True,
        validate=validate.Length(max=50)
    )

    value = fields.String(
        allow_none=True,
        validate=validate.Length(max=30)
    )

    size_system = fields.String(
        allow_none=True,
        load_default="INT",
        validate=validate.Length(max=20)
    )

    description = fields.String(allow_none=True)
    is_active = fields.Boolean(load_default=True)


class SizeUpdateSchema(SizeRequestSchema):
    # Do not reset is_active when omitted.
    is_active = fields.Boolean()


class SizeResponseSchema(Schema):
    id = fields.Integer()
    name = fields.String(allow_none=True)
    value = fields.String(allow_none=True)
    size_system = fields.String(allow_none=True)
    description = fields.String(allow_none=True)
    is_active = fields.Boolean()

    # Cambodia-local time: YYYY-MM-DD HH:MM:SS
    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )
