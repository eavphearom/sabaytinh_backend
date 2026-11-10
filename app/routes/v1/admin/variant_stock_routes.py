from flask import Blueprint,request
from flask_jwt_extended import get_jwt_identity
from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException
from app.schemas.variant_stock_schema import (VariantStockRequestSchema,VariantStockUpdateSchema,StockSetSchema,StockChangeSchema)
from app.services.variant_stock_service import VariantStockService
from app.security.decorators import admin_required
stock_bp=Blueprint('admin_variant_stocks',__name__,url_prefix='/api/v1/admin')
def body(schema):
    data=request.get_json(silent=True)
    if not isinstance(data,dict): raise BadRequestException('JSON object required')
    return schema.load(data)
@stock_bp.get('/variants/<int:variant_id>/stocks')
@admin_required
def list_stocks(variant_id): return ApiResponse.success(data=VariantStockService().list_by_variant(variant_id))
@stock_bp.get('/variant-stocks/<int:stock_id>')
@admin_required
def get_stock(stock_id): return ApiResponse.success(data=VariantStockService().get_by_id(stock_id))
@stock_bp.post('/variant-stocks')
@admin_required
def create_stock():
    result=VariantStockService().create(body(VariantStockRequestSchema()),int(get_jwt_identity()))
    return ApiResponse.success(data=result,message='Variant stock created',http_status=201)
@stock_bp.put('/variant-stocks/<int:stock_id>')
@admin_required
def update_stock(stock_id): return ApiResponse.success(data=VariantStockService().update(stock_id,body(VariantStockUpdateSchema()),int(get_jwt_identity())),message='Variant stock updated')
@stock_bp.put('/variant-stocks/<int:stock_id>/quantity')
@admin_required
def set_quantity(stock_id):
    data=body(StockSetSchema())
    result=VariantStockService().set_stock_quantity(stock_id,data['target_qty'],int(get_jwt_identity()),data.get('note'))
    return ApiResponse.success(data=result,message='Stock quantity updated')
@stock_bp.post('/variant-stocks/<int:stock_id>/increase')
@admin_required
def increase_stock(stock_id):
    data=body(StockChangeSchema())
    result=VariantStockService().increase_stock(stock_id,data['quantity'],int(get_jwt_identity()),data.get('unit_id'),data.get('reference_type','MANUAL_ADJUSTMENT'),data.get('reference_id'),data.get('note'))
    return ApiResponse.success(data=result,message='Stock increased')
@stock_bp.post('/variant-stocks/<int:stock_id>/deduct')
@admin_required
def deduct_stock(stock_id):
    data=body(StockChangeSchema())
    result=VariantStockService().deduct_stock(stock_id,data['quantity'],int(get_jwt_identity()),data.get('unit_id'),data.get('reference_type','MANUAL_ADJUSTMENT'),data.get('reference_id'),data.get('note'))
    return ApiResponse.success(data=result,message='Stock deducted')
