from marshmallow import Schema, fields


class CustomerResponseSchema(Schema):
    """Safe summary of the existing User model; not an authentication DTO."""

    id = fields.Integer()
    username = fields.String()
    email = fields.String()
    phone = fields.String(allow_none=True)
