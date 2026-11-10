
from flask import Blueprint
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.common.request_util import RequestUtil
from app.schemas.brand_schema import (
    BrandRequestSchema,
    BrandUpdateSchema,
)
from app.services.brand_service import BrandService
from app.security.decorators import admin_required


brand_bp = Blueprint(
    "admin_brands",
    __name__,
    url_prefix="/api/v1/admin/brands",
)


def get_request_data(partial=False):
    payload, logo_file = RequestUtil.get_payload("logo")

    schema = BrandUpdateSchema() if partial else BrandRequestSchema()
    data = schema.load(payload, partial=partial)

    return data, logo_file


@brand_bp.get("")
@admin_required
def get_brands():
    filters = BaseFilter.from_request(allow_deleted=True)
    result = BrandService().get_paginated(filters)

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"],
    )


@brand_bp.get("/<int:brand_id>")
@admin_required
def get_brand(brand_id):
    result = BrandService().get_by_id(brand_id)

    return ApiResponse.success(data=result)


@brand_bp.post("")
@admin_required
def create_brand():
    data, logo_file = get_request_data()

    result = BrandService().create(
        data=data,
        user_id=int(get_jwt_identity()),
        logo_file=logo_file,
    )

    return ApiResponse.success(
        data=result,
        message="Brand created successfully",
        http_status=201,
    )


@brand_bp.put("/<int:brand_id>")
@admin_required
def update_brand(brand_id):
    data, logo_file = get_request_data(partial=True)

    result = BrandService().update(
        brand_id=brand_id,
        data=data,
        user_id=int(get_jwt_identity()),
        logo_file=logo_file,
    )

    return ApiResponse.success(
        data=result,
        message="Brand updated successfully",
    )


@brand_bp.delete("/<int:brand_id>")
@admin_required
def delete_brand(brand_id):
    BrandService().delete(
        brand_id,
        user_id=int(get_jwt_identity()),
    )

    return ApiResponse.success(
        data=[],
        message="Brand deleted successfully",
    )
