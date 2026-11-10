from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity
from marshmallow import ValidationError

from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException
from app.schemas.delivery_method_schema import (
    DeliveryMethodRequestSchema,
)
from app.services.delivery_method_service import (
    DeliveryMethodService,
)
from app.security.decorators import admin_required


admin_delivery_method_bp = Blueprint(
    "admin_delivery_methods",
    __name__,
    url_prefix="/api/v1/admin/delivery-methods"
)


def _params():
    try:
        page = int(
            request.args.get(
                "page_no",
                request.args.get("pageNo", 1)
            )
        )

        size = int(
            request.args.get(
                "page_size",
                request.args.get("pageSize", 10)
            )
        )

    except (ValueError, TypeError):
        raise BadRequestException(
            "Invalid pagination parameters"
        )

    if page < 1 or size < 1 or size > 100:
        raise BadRequestException(
            "page_no must be >= 1 and page_size must be 1-100"
        )

    return (
        page,
        size,
        request.args.get("search", "").strip()
    )


def _payload():
    if request.mimetype != "multipart/form-data":
        raise BadRequestException(
            "multipart/form-data is required"
        )

    expected = {
        "name",
        "fee",
        "currency",
        "estimated_min_days",
        "estimated_max_days",
        "is_active",
    }

    if (
        set(request.form) - expected
        or set(request.files) - {"logo"}
    ):
        raise BadRequestException(
            "Unsupported delivery method fields"
        )

    for key in request.form.keys():
        if len(request.form.getlist(key)) != 1:
            raise BadRequestException(
                "Duplicate field: " + key
            )

    if len(request.files.getlist("logo")) > 1:
        raise BadRequestException(
            "Only one logo is allowed"
        )

    try:
        data = DeliveryMethodRequestSchema().load(
            request.form.to_dict()
        )

    except ValidationError as exc:
        raise BadRequestException(
            str(exc.messages)
        ) from exc

    return data, request.files.get("logo")


@admin_delivery_method_bp.get("")
@admin_delivery_method_bp.get("/pagination")
@admin_required
def list_methods():
    page, size, search = _params()

    result = DeliveryMethodService().get_paginated(
        page,
        size,
        search
    )

    return ApiResponse.paginate(
        data=result["items"],
        page_no=result["page_no"],
        per_page=result["page_size"],
        total=result["total_items"],
        total_page=result["total_pages"]
    )

@admin_delivery_method_bp.get("/<int:delivery_id>")
@admin_required
def get_method(delivery_id):
    result = DeliveryMethodService().get_by_id(
        delivery_id
    )

    return ApiResponse.success(data=result)


@admin_delivery_method_bp.post("")
@admin_required
def create_method():
    data, logo = _payload()

    result = DeliveryMethodService().create(
        data,
        logo,
        int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Delivery method created successfully",
        http_status=201
    )


@admin_delivery_method_bp.put("/<int:delivery_id>")
@admin_required
def update_method(delivery_id):
    data, logo = _payload()

    result = DeliveryMethodService().update(
        delivery_id,
        data,
        logo,
        int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Delivery method updated successfully"
    )


@admin_delivery_method_bp.delete("/<int:delivery_id>")
@admin_required
def delete_method(delivery_id):
    reason = request.args.get("reason")

    DeliveryMethodService().delete(
        delivery_id,
        int(get_jwt_identity()),
        reason
    )

    return ApiResponse.success(
        data=[],
        message="Delivery method deleted successfully"
    )