from flask import Blueprint
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.common.request_util import RequestUtil
from app.schemas.banner_schema import (
    BannerRequestSchema,
    BannerUpdateSchema,
)
from app.services.banner_service import BannerService
from app.security.decorators import admin_required


banner_bp = Blueprint(
    "admin_banners",
    __name__,
    url_prefix="/api/v1/admin/banners"
)


def get_request_data(partial=False):
    payload, image_file = RequestUtil.get_payload("image")

    schema = (
        BannerUpdateSchema()
        if partial
        else BannerRequestSchema()
    )

    data = schema.load(payload, partial=partial)

    return data, image_file


@banner_bp.get("")
@admin_required
def get_banners():
    filters = BaseFilter.from_request(allow_deleted=True)
    result = BannerService().get_paginated(filters)

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"]
    )


@banner_bp.get("/<int:banner_id>")
@admin_required
def get_banner(banner_id):
    return ApiResponse.success(
        data=BannerService().get_by_id(banner_id)
    )


@banner_bp.post("")
@admin_required
def create_banner():
    data, image_file = get_request_data()

    result = BannerService().create(
        data=data,
        user_id=int(get_jwt_identity()),
        image_file=image_file
    )

    return ApiResponse.success(
        data=result,
        message="Banner created successfully",
        http_status=201
    )


@banner_bp.put("/<int:banner_id>")
@admin_required
def update_banner(banner_id):
    data, image_file = get_request_data(partial=True)

    result = BannerService().update(
        banner_id=banner_id,
        data=data,
        user_id=int(get_jwt_identity()),
        image_file=image_file
    )

    return ApiResponse.success(
        data=result,
        message="Banner updated successfully"
    )


@banner_bp.delete("/<int:banner_id>")
@admin_required
def delete_banner(banner_id):
    BannerService().delete(
        banner_id,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=[],
        message="Banner deleted successfully"
    )
