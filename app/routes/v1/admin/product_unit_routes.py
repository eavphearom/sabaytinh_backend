
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.schemas.product_unit_schema import (
    ProductUnitRequestSchema,
    ProductUnitUpdateSchema,
)
from app.services.product_unit_service import ProductUnitService
from app.security.decorators import admin_required
from app.exceptions.api_exception import BadRequestException


product_unit_bp = Blueprint(
    "admin_product_units",
    __name__,
    url_prefix="/api/v1/admin/products"
)


def get_request_data(schema):
    data = request.get_json(silent=True)

    if not isinstance(data, dict):
        raise BadRequestException("Invalid JSON request body")

    return schema.load(data)


@product_unit_bp.get("/<int:product_id>/units")
@admin_required
def get_product_units(product_id):
    result = ProductUnitService().get_by_product(product_id)

    return ApiResponse.success(data=result)


@product_unit_bp.post("/<int:product_id>/units")
@admin_required
def create_product_unit(product_id):
    data = get_request_data(ProductUnitRequestSchema())

    result = ProductUnitService().create(
        product_id=product_id,
        data=data,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Product unit created successfully",
        http_status=201
    )


@product_unit_bp.put(
    "/<int:product_id>/units/<int:product_unit_id>"
)
@admin_required
def update_product_unit(product_id, product_unit_id):
    data = get_request_data(ProductUnitUpdateSchema())

    result = ProductUnitService().update(
        product_id=product_id,
        product_unit_id=product_unit_id,
        data=data,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Product unit updated successfully"
    )


@product_unit_bp.delete(
    "/<int:product_id>/units/<int:product_unit_id>"
)
@admin_required
def delete_product_unit(product_id, product_unit_id):
    ProductUnitService().delete(
        product_id=product_id,
        product_unit_id=product_unit_id,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=[],
        message="Product unit deleted successfully"
    )
