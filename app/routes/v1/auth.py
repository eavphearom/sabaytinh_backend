
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
from app.repositories.user_repository import UserRepository
from app.utils.file_util import FileUtil


auth_bp = Blueprint(
    "auth",
    __name__,
    url_prefix="/api/v1/auth"
)


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

    user = UserRepository().find_by_id(user_id)

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
