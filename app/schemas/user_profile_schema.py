from marshmallow import Schema, fields, validate


class UserProfileUpdateSchema(Schema):
    username = fields.String(
        validate=validate.Length(min=3, max=100)
    )
    email = fields.Email(
        validate=validate.Length(max=150)
    )
    phone = fields.String(
        allow_none=True,
        validate=validate.Length(max=30)
    )