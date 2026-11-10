
from marshmallow import Schema, fields, validate, RAISE

from app.utils.file_util import FileUtil


class BannerRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    title = fields.String(
        required=True,
        validate=validate.Length(min=1, max=150)
    )

    subtitle = fields.String(
        allow_none=True,
        validate=validate.Length(max=255)
    )

    is_active = fields.Boolean(load_default=True)


class BannerUpdateSchema(BannerRequestSchema):
    is_active = fields.Boolean()


class BannerResponseSchema(Schema):
    id = fields.Integer()
    title = fields.String()
    subtitle = fields.String(allow_none=True)
    image = fields.Method("get_image_url")
    is_active = fields.Boolean()

    created_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    updated_at = fields.DateTime(
        format="%Y-%m-%d %H:%M:%S",
        allow_none=True
    )

    def get_image_url(self, obj):
        return FileUtil.get_image_url(obj.image)
