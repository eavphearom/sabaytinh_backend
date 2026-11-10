
from marshmallow import Schema, fields, validate, RAISE

from app.utils.file_util import FileUtil


class BrandRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=120)
    )

    logo = fields.String(
        allow_none=True,
        validate=validate.Length(max=500)
    )

    description = fields.String(allow_none=True)
    is_active = fields.Boolean(load_default=True)


class BrandUpdateSchema(BrandRequestSchema):
    # No default during partial updates.
    is_active = fields.Boolean()


class BrandResponseSchema(Schema):
    id = fields.Integer()
    name = fields.String()
    slug = fields.String()
    logo = fields.Method("get_logo_url")
    description = fields.String()
    is_active = fields.Boolean()
    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    def get_logo_url(self, obj):
        return FileUtil.get_image_url(obj.logo)
