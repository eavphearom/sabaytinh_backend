
from flask import Blueprint, request
from marshmallow import ValidationError
from flask_jwt_extended import (
    jwt_required,
    get_jwt,
    get_jwt_identity,
)

from app.common.api_response import ApiResponse
from app.services.auth.auth_service import AuthService
from app.schemas.auth_schema import (
    RegisterSchema,
    LoginSchema,
    RefreshTokenSchema,
)
from app.exceptions.api_exception import (
    BadRequestException,
    UnauthorizedException,
)
from app.utils.file_util import FileUtil
from app.security.jwt_utils import authenticated_user
from app.schemas.oauth_schema import OAuthStartSchema, OAuthLoginSchema
from app.services.auth.oauth_service import OAuthService
from urllib.parse import urlsplit


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/api/v1/auth"
)


@auth_bp.after_request
def auth_no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


def oauth_payload():
    from flask import current_app
    from app.exceptions.api_exception import ForbiddenException
    request.max_content_length = 16384
    redirect = current_app.config.get("GOOGLE_REDIRECT_URI", "")
    url = urlsplit(redirect)
    expected_origin = f"{url.scheme}://{url.netloc}"
    if not redirect:
        OAuthService().strategy("google").configuration()
    if request.headers.get("Origin") != expected_origin:
        raise ForbiddenException("Invalid login origin")
    return get_json_payload()


@auth_bp.post("/google/start")
def google_start():
    data = OAuthStartSchema().load(oauth_payload())
    return ApiResponse.success(data=OAuthService().start("google", data))


@auth_bp.post("/google/login")
def google_login():
    data = OAuthLoginSchema().load(oauth_payload())
    return ApiResponse.success(data=OAuthService().login("google", data), message="Login successful")


def get_json_payload():
    """Get and validate the JSON request body."""
    payload = request.get_json(silent=True)

    if not isinstance(payload, dict):
        raise BadRequestException(
            "Malformed or invalid JSON request body"
        )

    return payload


@auth_bp.post("/register")
def register():
    data = RegisterSchema().load(get_json_payload())

    result = AuthService().register(data)

    return ApiResponse.success(
        data=result,
        message="Registration successful",
        http_status=201
    )


@auth_bp.post("/login")
def login():
    data = LoginSchema().load(get_json_payload())

    result = AuthService().login(data)

    return ApiResponse.success(
        data=result,
        message="Login successful"
    )


@auth_bp.post("/refresh")
def refresh():
    data = RefreshTokenSchema().load(get_json_payload())

    result = AuthService().refresh(
        data["refresh_token"]
    )

    return ApiResponse.success(
        data=result,
        message="Token refreshed successfully"
    )


@auth_bp.post("/logout")
@jwt_required()
def logout():
    jwt_data = get_jwt()

    AuthService().logout(
        session_id=jwt_data.get("sid"),
        user_id=get_jwt_identity()
    )

    return ApiResponse.success(
        data=[],
        message="Logout successful"
    )


@auth_bp.get("/me")
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())

    user = authenticated_user(user_id)

    if (
        user is None
        or user.status != "ACTIVE"
        or user.role is None
        or user.role.is_deleted
        or not user.role.is_active
    ):
        raise UnauthorizedException(
            "User account is unavailable"
        )

    return ApiResponse.success(
        data={
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "role": user.role.code,
            "is_active": user.status == "ACTIVE",
            "phone": user.phone,
            "created_at": user.created_at.strftime("%Y-%m-%dT%H:%M:%S") if user.created_at else None,
            "profile": FileUtil.get_image_url(user.profile),
        }
    )
