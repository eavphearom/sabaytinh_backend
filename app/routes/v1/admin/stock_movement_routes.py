
from flask import Blueprint, request

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.services.stock_movement_service import (
    StockMovementService
)
from app.security.decorators import admin_required


movement_bp = Blueprint(
    "admin_stock_movements",
    __name__,
    url_prefix="/api/v1/admin/stock-movements"
)


@movement_bp.get("")
@admin_required
def get_stock_movements():
    filters = BaseFilter.from_request(allow_deleted=True)

    result = StockMovementService().get_paginated(
        filters=filters,
        params=request.args.to_dict()
    )

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"],
    )
