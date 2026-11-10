
from marshmallow import Schema, fields, validate, RAISE

from app.utils.file_util import FileUtil


# Request DTO
class CategoryRequestSchema(Schema):
    class Meta:
        unknown = RAISE

    name = fields.String(
        required=True,
        validate=validate.Length(min=1, max=150)
    )

    image = fields.String(
        allow_none=True,
        validate=validate.Length(max=500)
    )

    description = fields.String(allow_none=True)

    # Default to True if not supplied.
    is_active = fields.Boolean(load_default=True)



from marshmallow import Schema, fields
from app.utils.file_util import FileUtil


class CategoryResponseSchema(Schema):
    id = fields.Integer()
    name = fields.String()
    slug = fields.String()
    image = fields.Method("get_image_url")
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
    def get_image_url(self, obj):
        return FileUtil.get_image_url(obj.image)

