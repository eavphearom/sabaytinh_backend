
from flask import Blueprint
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.common.request_util import RequestUtil
from app.schemas.size_schema import (
    SizeRequestSchema,
    SizeUpdateSchema,
)
from app.services.size_service import SizeService
from app.security.decorators import admin_required


size_bp = Blueprint(
    "admin_sizes",
    __name__,
    url_prefix="/api/v1/admin/sizes"
)


def get_request_data(partial=False):
    # Accept JSON or multipart form data.
    payload, _ = RequestUtil.get_payload()

    schema = SizeUpdateSchema() if partial else SizeRequestSchema()

    return schema.load(payload, partial=partial)


@size_bp.get("")
@admin_required
def get_sizes():
    filters = BaseFilter.from_request(allow_deleted=True)
    result = SizeService().get_paginated(filters)

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"]
    )


@size_bp.get("/<int:size_id>")
@admin_required
def get_size(size_id):
    return ApiResponse.success(
        data=SizeService().get_by_id(size_id)
    )


@size_bp.post("")
@admin_required
def create_size():
    result = SizeService().create(
        data=get_request_data(),
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Size created successfully",
        http_status=201
    )


@size_bp.put("/<int:size_id>")
@admin_required
def update_size(size_id):
    result = SizeService().update(
        size_id=size_id,
        data=get_request_data(partial=True),
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Size updated successfully"
    )


@size_bp.delete("/<int:size_id>")
@admin_required
def delete_size(size_id):
    SizeService().delete(
        size_id,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=[],
        message="Size deleted successfully"
    )
