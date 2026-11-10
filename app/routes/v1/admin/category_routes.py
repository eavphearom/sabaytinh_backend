
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.schemas.category_schema import CategoryRequestSchema
from app.services.category_service import CategoryService
from app.security.decorators import admin_required
from app.exceptions.api_exception import BadRequestException
from marshmallow import ValidationError
from app.exceptions.api_exception import BadRequestException
from app.utils.file_upload import save_image
from app.common.request_util import RequestUtil
category_bp = Blueprint(
    "admin_categories",
    __name__,
    url_prefix="/api/v1/admin/categories"
)


def get_request_data(partial=False):
    payload, image_file = RequestUtil.get_payload()

    data = CategoryRequestSchema().load(
        payload,
        partial=partial
    )

    return data, image_file


@category_bp.get("")
@admin_required
def get_categories():
    filters = BaseFilter.from_request(allow_deleted=True)
    result = CategoryService().get_paginated(filters)

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"]
    )


@category_bp.get("/<int:category_id>")
@admin_required
def get_category(category_id):
    result = CategoryService().get_by_id(category_id)

    return ApiResponse.success(data=result)



@category_bp.post("")
@admin_required
def create_category():
    data, image_file = get_request_data()

    result = CategoryService().create(
        data=data,
        user_id=int(get_jwt_identity()),
        image_file=image_file,
    )

    return ApiResponse.success(
        data=result,
        message="Category created successfully",
        http_status=201
    )




@category_bp.put("/<int:category_id>")
@admin_required
def update_category(category_id):
    data, image_file = get_request_data(partial=True)

    result = CategoryService().update(
        category_id=category_id,
        data=data,
        user_id=int(get_jwt_identity()),
        image_file=image_file,
    )

    return ApiResponse.success(
        data=result,
        message="Category updated successfully"
    )



@category_bp.delete("/<int:category_id>")
@admin_required
def delete_category(category_id):
    CategoryService().delete(
        category_id,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=[],
        message="Category deleted successfully"
    )
