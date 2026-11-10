from marshmallow import Schema, fields


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
