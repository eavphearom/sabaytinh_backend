
from flask import Blueprint
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.common.request_util import RequestUtil
from app.schemas.color_schema import (
    ColorRequestSchema,
    ColorUpdateSchema,
)
from app.services.color_service import ColorService
from app.security.decorators import admin_required


color_bp = Blueprint(
    "admin_colors",
    __name__,
    url_prefix="/api/v1/admin/colors"
)


def get_request_data(partial=False):
    # Accept JSON or multipart form data.
    payload, _ = RequestUtil.get_payload()

    schema = ColorUpdateSchema() if partial else ColorRequestSchema()

    return schema.load(payload, partial=partial)


@color_bp.get("")
@admin_required
def get_colors():
    filters = BaseFilter.from_request(allow_deleted=True)
    result = ColorService().get_paginated(filters)

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"]
    )


@color_bp.get("/<int:color_id>")
@admin_required
def get_color(color_id):
    return ApiResponse.success(
        data=ColorService().get_by_id(color_id)
    )


@color_bp.post("")
@admin_required
def create_color():
    result = ColorService().create(
        data=get_request_data(),
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Color created successfully",
        http_status=201
    )


@color_bp.put("/<int:color_id>")
@admin_required
def update_color(color_id):
    result = ColorService().update(
        color_id=color_id,
        data=get_request_data(partial=True),
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Color updated successfully"
    )


@color_bp.delete("/<int:color_id>")
@admin_required
def delete_color(color_id):
    ColorService().delete(
        color_id,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=[],
        message="Color deleted successfully"
    )
