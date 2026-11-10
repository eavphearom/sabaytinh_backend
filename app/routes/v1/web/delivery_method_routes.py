from flask import Blueprint, request

from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException
from app.services.delivery_method_service import (
    DeliveryMethodService,
)


web_delivery_method_bp = Blueprint(
    "web_delivery_methods",
    __name__,
    url_prefix="/api/v1/web/delivery-methods"
)


@web_delivery_method_bp.get("")
def list_active_delivery_methods():
    try:
        page = int(
            request.args.get("page_no", 1)
        )
        size = int(
            request.args.get("page_size", 100)
        )

    except (TypeError, ValueError):
        raise BadRequestException(
            "Invalid pagination parameters"
        )

    if page < 1 or not (1 <= size <= 100):
        raise BadRequestException(
            "Invalid pagination parameters"
        )

    result = DeliveryMethodService().get_paginated(
        page,
        size,
        request.args.get("search"),
        active_only=True
    )

    return ApiResponse.success(
        data=result["items"],
        message="success"
    )