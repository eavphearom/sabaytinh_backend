from flask import Blueprint, request

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.exceptions.api_exception import BadRequestException
from app.schemas.web_home_schema import HomeProductFilterSchema
from app.services.web_home_service import WebHomeService


web_home_bp = Blueprint("web_home", __name__, url_prefix="/api/v1/web/home")


@web_home_bp.get("/products")
def products():
    filters = BaseFilter.from_request()
    schema = HomeProductFilterSchema()
    params = schema.load({key: request.args[key] for key in schema.fields if key in request.args})
    if params.get("type") == "new" and "per_page" not in request.args:
        filters.per_page = 15
    if (filters.page_no - 1) * filters.per_page > 9223372036854775807:
        raise BadRequestException("Requested page offset is too large")
    result = WebHomeService().products(filters, params)
    return ApiResponse.paginate(data=result["items"], per_page=result["per_page"],
        total=result["total"], total_page=result["total_page"], page_no=result["page_no"])


@web_home_bp.get("/banners")
def banners():
    return ApiResponse.success(data=WebHomeService().banners())


@web_home_bp.get("/products/<product_id>")
def product_detail(product_id):
    # String converter permits consistent 400 responses for malformed IDs.
    return ApiResponse.success(data=WebHomeService().product_detail(product_id))
