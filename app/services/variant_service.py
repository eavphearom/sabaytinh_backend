from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.product import Product
from app.models.color import Color
from app.models.variant import Variant
from app.repositories.variant_repository import VariantRepository
from app.schemas.variant_schema import VariantResponseSchema
from app.utils.date_util import DateUtil
from app.exceptions.api_exception import BadRequestException, DuplicateException, ResourceNotFoundException

class VariantService:
    def __init__(self):
        self.repo=VariantRepository(); self.schema=VariantResponseSchema()
    def get_by_id(self, variant_id):
        v=self.repo.find_by_id(variant_id)
        if v is None: raise ResourceNotFoundException("Variant not found")
        return self.schema.dump(v)
    def list_by_product(self, product_id):
        return self.schema.dump(self.repo.by_product(product_id), many=True)
    def _validate(self, product_id, color_id):
        p=db.session.get(Product,product_id)
        c=db.session.get(Color,color_id)
        if p is None or p.is_deleted: raise BadRequestException("Product not found")
        if c is None or c.is_deleted: raise BadRequestException("Color not found")
    def create(self,data,user_id):
        data=data.copy(); data['sku_prefix']=data['sku_prefix'].strip()
        if not data['sku_prefix']: raise BadRequestException("SKU prefix required")
        self._validate(data['product_id'],data['color_id'])
        if self.repo.by_product_color(data['product_id'],data['color_id']):
            raise DuplicateException("Variant product/color already exists")
        try:
            v=Variant(**data,create_uid=user_id,created_at=DateUtil.now())
            db.session.add(v);db.session.flush(); result=self.schema.dump(v);db.session.commit();return result
        except IntegrityError as e:
            db.session.rollback();raise DuplicateException("Variant product/color or default already exists") from e
        except Exception:
            db.session.rollback();raise
    def update(self,variant_id,data,user_id):
        v=self.repo.find_by_id(variant_id)
        if v is None: raise ResourceNotFoundException("Variant not found")
        data=data.copy()
        if 'sku_prefix' in data:
            data['sku_prefix']=data['sku_prefix'].strip()
            if not data['sku_prefix']: raise BadRequestException("SKU prefix required")
        if 'color_id' in data:
            self._validate(v.product_id,data['color_id'])
        try:
            for key,value in data.items(): setattr(v,key,value)
            v.updated_at=DateUtil.now();v.update_uid=user_id
            db.session.flush();result=self.schema.dump(v);db.session.commit();return result
        except IntegrityError as e:
            db.session.rollback();raise DuplicateException("Variant product/color or default already exists") from e
        except Exception:
            db.session.rollback();raise
    def delete(self,variant_id,user_id):
        # Prevent deleting variants with tracked stock; preserve order/inventory history.
        from sqlalchemy import select
        from app.models.variant_stock import VariantStock
        v=self.repo.find_by_id(variant_id)
        if v is None: raise ResourceNotFoundException("Variant not found")
        if db.session.scalar(select(VariantStock.id).where(VariantStock.variant_id==variant_id).limit(1)) is not None:
            raise BadRequestException("Cannot delete variant with stock records")
        try:
            self.repo.soft_delete_by_id(variant_id,deleted_uid=user_id)
            db.session.commit()
        except Exception:
            db.session.rollback();raise
