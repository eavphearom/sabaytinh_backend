from app.common.filters import pagination_params
from flask import Blueprint, request

from app.common.api_response import ApiResponse
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
    page, size = pagination_params(request.args, default_size=100, size_aliases=("page_size",))

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