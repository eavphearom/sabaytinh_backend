from flask import Blueprint, request
from app.routes.v1.order_route_util import paginated
from app.security.decorators import admin_required
from app.services.admin_user_service import AdminUserService

admin_user_bp = Blueprint("admin_users", __name__, url_prefix="/api/v1/admin/users")


@admin_user_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_user_bp.get("")
@admin_required
def list_users():
    return paginated(AdminUserService().get_paginated(request.args))
