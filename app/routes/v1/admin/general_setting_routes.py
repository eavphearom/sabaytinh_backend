from flask import Blueprint

from app.common.api_response import ApiResponse
from app.security.decorators import admin_required
from app.services.general_setting_service import GeneralSettingService


admin_setting_bp = Blueprint("admin_settings", __name__, url_prefix="/api/v1/admin/setting")


@admin_setting_bp.get("/form/product")
@admin_required
def product_form():
    return ApiResponse.success(data=GeneralSettingService().product_form())


@admin_setting_bp.get("/filter/product")
@admin_required
def product_filters():
    return ApiResponse.success(data=GeneralSettingService().product_filters())


@admin_setting_bp.get("/filter/stock-movement")
@admin_required
def stock_movement_filters():
    return ApiResponse.success(data=GeneralSettingService().stock_movement_filters())


@admin_setting_bp.get("/filter/order")
@admin_required
def order_filters():
    return ApiResponse.success(data=GeneralSettingService().admin_order_filters())
