from flask import Blueprint
from app.common.api_response import ApiResponse
from app.security.decorators import admin_required
from app.services.dashboard_service import DashboardService

admin_dashboard_bp = Blueprint("admin_dashboard", __name__, url_prefix="/api/v1/admin/dashboard")


@admin_dashboard_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_dashboard_bp.get("/overview")
@admin_required
def overview():
    return ApiResponse.success(data=DashboardService().overview())
