
from marshmallow import Schema, fields, validate


class RegisterSchema(Schema):
    username = fields.String(
        required=True,
        validate=validate.Length(min=1, max=100)
    )

    email = fields.Email(
        required=True,
        validate=validate.Length(max=150)
    )

    password = fields.String(
        required=True,
        load_only=True,
        validate=validate.Length(min=8, max=72)
    )

    phone = fields.String(
        allow_none=True,
        load_default=None,
        validate=validate.Length(max=30)
    )

class LoginSchema(Schema):
    email = fields.Email(required=True)
    password = fields.String(required=True, load_only=True)


class RefreshTokenSchema(Schema):
    refresh_token = fields.String(
        required=True,
        validate=validate.Length(min=1)
    )


class LogoutSchema(RefreshTokenSchema):
    pass
