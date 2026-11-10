from flask import Blueprint, request
from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity,
)
from marshmallow import ValidationError

from app.common.api_response import ApiResponse
from app.schemas.user_profile_schema import UserProfileUpdateSchema
from app.services.user_profile_service import UserProfileService
from app.exceptions.api_exception import BadRequestException


user_profile_bp = Blueprint(
    "user_profile",
    __name__,
    url_prefix="/api/v1/users"
)


@user_profile_bp.put("/me")
@jwt_required()
def update_my_profile():
    if request.mimetype != "multipart/form-data":
        raise BadRequestException(
            "multipart/form-data is required"
        )

    allowed = {"username", "email", "phone"}

    unknown = set(request.form.keys()) - allowed

    if unknown:
        raise BadRequestException(
            "Unsupported fields: "
            + ", ".join(sorted(unknown))
        )

    unexpected_files = (
        set(request.files.keys()) - {"profile"}
    )

    if unexpected_files:
        raise BadRequestException(
            "Only the profile image field is supported"
        )

    for key in request.form.keys():
        if len(request.form.getlist(key)) != 1:
            raise BadRequestException(
                "Duplicate field: " + key
            )

    try:
        data = UserProfileUpdateSchema().load(
            request.form.to_dict()
        )

    except ValidationError as exc:
        raise BadRequestException(
            str(exc.messages)
        ) from exc

    profile_file = request.files.get("profile")

    result = UserProfileService().update_me(
        int(get_jwt_identity()),
        data,
        profile_file
    )

    return ApiResponse.success(
        data=result,
        message="Profile updated successfully"
    )