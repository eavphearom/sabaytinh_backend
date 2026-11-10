from marshmallow import Schema, fields, RAISE
from app.utils.file_util import FileUtil
class VariantImageRequestSchema(Schema):
    class Meta: unknown = RAISE
    is_primary = fields.Boolean(load_default=False)
class VariantImageResponseSchema(Schema):
    id = fields.Integer()
    variant_id = fields.Integer()
    image = fields.Method("image_url")
    is_primary = fields.Boolean()
    created_at = fields.DateTime(format="%Y-%m-%d %H:%M:%S", allow_none=True)
    def image_url(self, obj):
        return FileUtil.get_image_url(obj.image)
