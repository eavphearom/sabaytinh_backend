from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.routes.v1.order_route_util import json_payload, paginated
from app.schemas.order_schema import (
    OrderCancelRequestSchema, OrderStatusUpdateRequestSchema, PaymentStatusUpdateRequestSchema,
)
from app.security.decorators import admin_required
from app.services.order_service import OrderService


admin_order_bp = Blueprint("admin_orders", __name__, url_prefix="/api/v1/admin/orders")


@admin_order_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@admin_order_bp.get("")
@admin_required
def list_orders():
    return paginated(OrderService().get_paginated(
        BaseFilter.from_request(allow_deleted=True), request.args.to_dict()))


@admin_order_bp.get("/<int:order_id>")
@admin_required
def detail(order_id):
    return ApiResponse.success(data=OrderService().get_detail(order_id))


@admin_order_bp.patch("/<int:order_id>/status")
@admin_required
def update_status(order_id):
    data = OrderStatusUpdateRequestSchema().load(json_payload())
    return ApiResponse.success(data=OrderService().update_status(
        order_id, data["order_status"], data.get("note"), int(get_jwt_identity())))


@admin_order_bp.patch("/<int:order_id>/cancel")
@admin_required
def cancel(order_id):
    data = OrderCancelRequestSchema().load(json_payload())
    return ApiResponse.success(data=OrderService().cancel(
        order_id, int(get_jwt_identity()), data["reason"], admin=True), message="Order cancelled")


@admin_order_bp.patch("/<int:order_id>/payment-status")
@admin_required
def update_payment_status(order_id):
    PaymentStatusUpdateRequestSchema().load(json_payload())
    return OrderService().manage_payment_status(order_id)


@admin_order_bp.delete("/<int:order_id>")
@admin_required
def delete(order_id):
    OrderService().delete(order_id, int(get_jwt_identity()), request.args.get("reason"))
    return ApiResponse.success(data=[], message="Order deleted")
