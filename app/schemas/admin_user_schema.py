from marshmallow import Schema, fields


class AdminUserResponseSchema(Schema):
    id = fields.Integer()
    username = fields.String()
    email = fields.String()
    role = fields.String()
    is_active = fields.Boolean()
