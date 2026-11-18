from marshmallow import Schema, fields
from app.utils.file_util import FileUtil


class SettingOptionSchema(Schema):
    id = fields.Integer()
    name = fields.String(allow_none=True)


class SettingSizeSchema(SettingOptionSchema):
    value = fields.String(allow_none=True)


class SettingDeliverySchema(SettingOptionSchema):
    # This lookup contract requests a JSON number, unlike the full delivery DTO.
    # Do not round the stored fee or change checkout's Decimal calculation.
    fee = fields.Float()
    currency = fields.String()
    image = fields.Method("image_url")

    def image_url(self, obj):
        return FileUtil.get_image_url(obj.logo)
