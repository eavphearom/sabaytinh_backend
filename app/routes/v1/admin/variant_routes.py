from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity
from app.common.api_response import ApiResponse
from app.schemas.variant_schema import VariantRequestSchema, VariantUpdateSchema
from app.services.variant_service import VariantService
from app.security.decorators import admin_required
from app.exceptions.api_exception import BadRequestException
variant_bp=Blueprint('admin_variants',__name__,url_prefix='/api/v1/admin')
def body(schema):
    data=request.get_json(silent=True)
    if not isinstance(data,dict): raise BadRequestException('JSON object required')
    return schema.load(data)
@variant_bp.get('/products/<int:product_id>/variants')
@admin_required
def list_variants(product_id): return ApiResponse.success(data=VariantService().list_by_product(product_id))
@variant_bp.get('/variants/<int:variant_id>')
@admin_required
def get_variant(variant_id): return ApiResponse.success(data=VariantService().get_by_id(variant_id))
@variant_bp.post('/variants')
@admin_required
def create_variant(): return ApiResponse.success(data=VariantService().create(body(VariantRequestSchema()),int(get_jwt_identity())),message='Variant created successfully',http_status=201)
@variant_bp.put('/variants/<int:variant_id>')
@admin_required
def update_variant(variant_id): return ApiResponse.success(data=VariantService().update(variant_id,body(VariantUpdateSchema()),int(get_jwt_identity())),message='Variant updated successfully')
@variant_bp.delete('/variants/<int:variant_id>')
@admin_required
def delete_variant(variant_id):
    VariantService().delete(variant_id,int(get_jwt_identity()))
    return ApiResponse.success(data=[],message='Variant deleted successfully')
