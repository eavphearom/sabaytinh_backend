from flask import Blueprint

from app.common.api_response import ApiResponse
from app.services.general_setting_service import GeneralSettingService


web_setting_bp = Blueprint("web_settings", __name__, url_prefix="/api/v1/web/setting")


@web_setting_bp.get("/filter/shop")
def shop_filters():
    return ApiResponse.success(data=GeneralSettingService().product_filters())


@web_setting_bp.get("/form/order")
def order_form():
    return ApiResponse.success(data=GeneralSettingService().order_form())


@web_setting_bp.get("/filter/order")
def order_filters():
    return ApiResponse.success(data=GeneralSettingService().web_order_filters())
