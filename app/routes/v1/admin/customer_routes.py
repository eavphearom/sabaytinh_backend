from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.exceptions.api_exception import BadRequestException
from app.routes.v1.order_route_util import paginated
from app.security.decorators import admin_required
from app.services.customer_service import CustomerService

admin_customer_bp = Blueprint("admin_customers", __name__, url_prefix="/api/v1/admin/customers")


@admin_customer_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_customer_bp.get("")
@admin_required
def list_customers():
    if any(key not in {"page_no", "per_page", "search"} or len(request.args.getlist(key)) != 1 for key in request.args):
        raise BadRequestException("Unsupported or repeated customer filter")
    return paginated(CustomerService().get_paginated(BaseFilter.from_request()))


@admin_customer_bp.get("/<int:customer_id>")
@admin_required
def detail(customer_id):
    return ApiResponse.success(data=CustomerService().get_detail(customer_id))


@admin_customer_bp.delete("/<int:customer_id>")
@admin_required
def delete(customer_id):
    CustomerService().delete(customer_id, int(get_jwt_identity()))
    return ApiResponse.success(data=[], message="Customer deleted")
