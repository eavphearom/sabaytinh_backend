from marshmallow import Schema, fields, validate


class OAuthStartSchema(Schema):
    code_challenge = fields.String(required=True, validate=validate.Regexp(r"^[A-Za-z0-9_-]{43}$"))


class OAuthLoginSchema(Schema):
    code = fields.String(required=True, validate=validate.Length(min=1, max=4096))
    state = fields.String(required=True, validate=validate.Length(min=1, max=4096))
    code_verifier = fields.String(required=True, validate=validate.Regexp(r"^[A-Za-z0-9._~-]{43,128}$"))
