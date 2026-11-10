
from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.mappers.product_request_mapper import ProductRequestMapper
from app.services.product_service import ProductService
from app.security.decorators import admin_required


product_bp = Blueprint(
    "admin_products",
    __name__,
    url_prefix="/api/v1/admin/products"
)


# Get products with pagination, search, and filters
@product_bp.get("")
@product_bp.get("/pagination")
@admin_required
def get_products():
    filters = BaseFilter.from_request(allow_deleted=True)

    result = ProductService().get_paginated(
        filters=filters,
        params=request.args.to_dict()
    )

    return ApiResponse.paginate(
        data=result["items"],
        per_page=result["per_page"],
        total=result["total"],
        total_page=result["total_page"],
        page_no=result["page_no"]
    )

# Get complete product stock overview
@product_bp.get("/<int:product_id>/stocks")
@admin_required
def get_product_stock_detail(product_id):
    result = ProductService().get_stock_detail(product_id)

    return ApiResponse.success(data=result)


# Get complete product details
@product_bp.get("/<int:product_id>")
@admin_required
def get_product(product_id):
    result = ProductService().get_by_id(product_id)

    return ApiResponse.success(data=result)


# Create product with variants, stocks, and images
@product_bp.post("")
@admin_required
def create_product():
    data = ProductRequestMapper.parse()

    result = ProductService().create(
        data=data,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Product created successfully",
        http_status=201
    )


# Update complete product
@product_bp.put("/<int:product_id>")
@admin_required
def update_product(product_id):
    data = ProductRequestMapper.parse()

    result = ProductService().update(
        product_id=product_id,
        data=data,
        user_id=int(get_jwt_identity())
    )

    return ApiResponse.success(
        data=result,
        message="Product updated successfully"
    )


# Soft delete product
@product_bp.delete("/<int:product_id>")
@admin_required
def delete_product(product_id):
    reason = request.args.get("reason")

    ProductService().delete(
        product_id=product_id,
        user_id=int(get_jwt_identity()),
        reason=reason
    )

    return ApiResponse.success(
        data=[],
        message="Product deleted successfully"
    )
