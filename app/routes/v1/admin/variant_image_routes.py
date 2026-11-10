from flask import Blueprint, request
from flask_jwt_extended import get_jwt_identity
from app.common.api_response import ApiResponse
from app.common.request_util import RequestUtil
from app.schemas.variant_image_schema import VariantImageRequestSchema
from app.services.variant_image_service import VariantImageService
from app.security.decorators import admin_required
image_bp=Blueprint('admin_variant_images',__name__,url_prefix='/api/v1/admin/variants')
@image_bp.get('/<int:variant_id>/images')
@admin_required
def get_images(variant_id): return ApiResponse.success(data=VariantImageService().list_by_variant(variant_id))
@image_bp.post('/<int:variant_id>/images')
@admin_required
def upload_image(variant_id):
    payload,image_file=RequestUtil.get_payload('image')
    data=VariantImageRequestSchema().load(payload)
    result=VariantImageService().create(variant_id,data,image_file,int(get_jwt_identity()))
    return ApiResponse.success(data=result,message='Variant image uploaded successfully',http_status=201)
@image_bp.put('/<int:variant_id>/images/<int:image_id>/primary')
@admin_required
def primary_image(variant_id,image_id):
    return ApiResponse.success(data=VariantImageService().set_primary(variant_id,image_id,int(get_jwt_identity())),message='Primary image updated')
@image_bp.delete('/<int:variant_id>/images/<int:image_id>')
@admin_required
def remove_image(variant_id,image_id):
    VariantImageService().delete(variant_id,image_id,int(get_jwt_identity()))
    return ApiResponse.success(data=[],message='Variant image deleted')
