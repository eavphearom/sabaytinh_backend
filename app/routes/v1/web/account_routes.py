from flask import Blueprint, g, request

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.exceptions.api_exception import BadRequestException
from app.routes.v1.order_route_util import paginated
from app.security.decorators import customer_required
from app.services.web_account_service import WebAccountService


web_account_bp = Blueprint("web_account", __name__, url_prefix="/api/v1/web/account")


@web_account_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@web_account_bp.get("/overview")
@customer_required
def overview():
    if request.args:
        raise BadRequestException("Account overview does not accept query parameters")
    return ApiResponse.success(data=WebAccountService().overview(g.customer_id))


@web_account_bp.get("/orders")
@customer_required
def orders():
    allowed = {"page_no", "per_page", "search", "status", "sort_by", "sort_dir"}
    if set(request.args) - allowed or any(len(request.args.getlist(key)) != 1 for key in request.args):
        raise BadRequestException("Unknown or repeated account order filter")
    filters = BaseFilter.from_request()
    if "sort_by" not in request.args:
        filters.sort_by = "createdAt"
    return paginated(WebAccountService().orders(g.customer_id, filters, request.args.get("status")))
