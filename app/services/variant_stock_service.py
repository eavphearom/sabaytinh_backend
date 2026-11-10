from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models.product import Product
from app.models.size import Size
from app.models.unit import Unit
from app.models.product_unit import ProductUnit
from app.models.variant import Variant
from app.models.variant_stock import VariantStock
from app.models.stock_movement import StockMovement
from app.repositories.variant_stock_repository import VariantStockRepository
from app.schemas.variant_stock_schema import VariantStockResponseSchema
from app.utils.date_util import DateUtil
from app.exceptions.api_exception import BadRequestException, DuplicateException, ResourceNotFoundException
from app.enums.stock_movement_type import StockMovementType
from app.enums.stock_reference_type import StockReferenceType

MAX_QTY=2147483647
class VariantStockService:
    def __init__(self):
        self.repo=VariantStockRepository();self.schema=VariantStockResponseSchema()
    def list_by_variant(self,variant_id):
        return self.schema.dump(self.repo.by_variant(variant_id),many=True)
    def get_by_id(self,stock_id):
        s=self.repo.find_by_id(stock_id)
        if s is None: raise ResourceNotFoundException("Variant stock not found")
        return self.schema.dump(s)
    def create(self,data,user_id):
        variant=db.session.get(Variant,data['variant_id'])
        size=db.session.get(Size,data['size_id'])
        if variant is None or variant.is_deleted: raise BadRequestException("Variant not found")
        if size is None or size.is_deleted: raise BadRequestException("Size not found")
        product=db.session.get(Product,variant.product_id)
        if product is None or product.is_deleted: raise BadRequestException("Product not found")
        base=db.session.scalar(select(ProductUnit).where(ProductUnit.product_id==product.id,ProductUnit.unit_id==product.unit_id,ProductUnit.is_deleted.is_(False)))
        if base is None or base.multiplier != Decimal('1'): raise BadRequestException("Product base unit (multiplier 1) must be configured")
        sku=data['sku'].strip()
        if not sku: raise BadRequestException("SKU required")
        try:
            s=VariantStock(variant_id=variant.id,size_id=size.id,unit_id=product.unit_id,sku=sku,qty=0,
                low_stock_alert=data.get('low_stock_alert',0),created_at=DateUtil.now(),create_uid=user_id)
            db.session.add(s);db.session.flush();result=self.schema.dump(s);db.session.commit();return result
        except IntegrityError as e:
            db.session.rollback();raise DuplicateException("Variant size already exists") from e
        except Exception:
            db.session.rollback();raise
    def update(self,stock_id,data,user_id):
        s=self.repo.find_by_id(stock_id)
        if s is None: raise ResourceNotFoundException("Variant stock not found")
        try:
            for key,value in data.items():
                if key=='sku':
                    value=value.strip()
                    if not value: raise BadRequestException("SKU required")
                setattr(s,key,value)
            s.updated_at=DateUtil.now();s.update_uid=user_id
            db.session.flush();result=self.schema.dump(s);db.session.commit();return result
        except Exception:
            db.session.rollback();raise
    def _locked(self,stock_id):
        s=self.repo.for_update(stock_id)
        if s is None: raise ResourceNotFoundException("Variant stock not found")
        return s
    def _apply(self,s,kind,quantity,unit_id,ref_type,reference_id,note,user_id):
        if type(quantity) is not int or quantity<=0: raise BadRequestException("Quantity must be greater than zero")
        variant=db.session.get(Variant,s.variant_id)
        if variant is None or variant.is_deleted: raise ResourceNotFoundException("Variant not found")
        tx_unit_id=unit_id if unit_id is not None else s.unit_id
        pu=db.session.scalar(select(ProductUnit).where(ProductUnit.product_id==variant.product_id,ProductUnit.unit_id==tx_unit_id,ProductUnit.is_deleted.is_(False)))
        if pu is None: raise BadRequestException("Unit is not configured for this product")
        multiplier=pu.multiplier
        if multiplier is None or multiplier<=0: raise BadRequestException("Invalid multiplier")
        base_unit=db.session.scalar(select(ProductUnit).where(ProductUnit.product_id==variant.product_id,ProductUnit.unit_id==s.unit_id,ProductUnit.is_deleted.is_(False)))
        if base_unit is None or base_unit.multiplier!=Decimal('1'): raise BadRequestException("Stock base unit must be configured at multiplier 1")
        converted=Decimal(quantity)*multiplier
        if converted!=converted.to_integral_value() or converted<=0 or converted>MAX_QTY:
            raise BadRequestException("Converted quantity must be a positive whole number within stock limit")
        change=int(converted)
        before=s.qty
        after=before+change if kind=='IN' else before-change
        if after<0: raise BadRequestException("Insufficient stock")
        if after>MAX_QTY: raise BadRequestException("Stock quantity exceeds allowed limit")
        s.qty=after;s.updated_at=DateUtil.now();s.update_uid=user_id
        movement=StockMovement(variant_stock_id=s.id,unit_id=tx_unit_id,type=kind,qty_change=quantity,
            multiplier=multiplier,base_qty_change=change,qty_before=before,qty_after=after,
            reference_type=ref_type.value if isinstance(ref_type,StockReferenceType) else ref_type,
            reference_id=reference_id,note=note,created_at=DateUtil.now(),create_uid=user_id)
        db.session.add(movement)
    def change(self,stock_id,kind,quantity,user_id,unit_id=None,reference_type=StockReferenceType.MANUAL_ADJUSTMENT,reference_id=None,note=None):
        try:
            s=self._locked(stock_id)
            if kind not in ('IN','OUT'): raise BadRequestException("Unsupported movement type")
            self._apply(s,kind,quantity,unit_id,reference_type,reference_id,note,user_id)
            db.session.flush();result=self.schema.dump(s);db.session.commit();return result
        except Exception:
            db.session.rollback();raise
    def increase_stock(self,stock_id,quantity,user_id,unit_id=None,reference_type=StockReferenceType.MANUAL_ADJUSTMENT,reference_id=None,note=None):
        return self.change(stock_id,'IN',quantity,user_id,unit_id,reference_type,reference_id,note)
    def deduct_stock(self,stock_id,quantity,user_id,unit_id=None,reference_type=StockReferenceType.MANUAL_ADJUSTMENT,reference_id=None,note=None):
        return self.change(stock_id,'OUT',quantity,user_id,unit_id,reference_type,reference_id,note)
    def has_enough_stock(self,stock_id,quantity):
        if type(quantity) is not int or quantity<=0: raise BadRequestException("Quantity must be greater than zero")
        s=self.repo.find_by_id(stock_id)
        if s is None: raise ResourceNotFoundException("Variant stock not found")
        return s.qty>=quantity
    def set_stock_quantity(self,stock_id,target_qty,user_id,note=None):
        if type(target_qty) is not int or target_qty<0 or target_qty>MAX_QTY:
            raise BadRequestException("Stock quantity must be between 0 and 2147483647")
        try:
            s=self._locked(stock_id)
            difference=target_qty-s.qty
            if difference:
                self._apply(s,'IN' if difference>0 else 'OUT',abs(difference),None,
                    StockReferenceType.MANUAL_ADJUSTMENT,None,note,user_id)
            db.session.flush();result=self.schema.dump(s);db.session.commit();return result
        except Exception:
            db.session.rollback();raise
    def lock_order_stocks(self, quantities, restore=False):
        """Validate and lock base-unit quantities in the caller's transaction."""
        if not quantities:
            raise BadRequestException("Order items required")
        for stock_id, quantity in quantities.items():
            if type(stock_id) is not int or not 1 <= stock_id <= 9_223_372_036_854_775_807:
                raise BadRequestException("Invalid variant stock ID")
            if type(quantity) is not int or not 1 <= quantity <= MAX_QTY:
                raise BadRequestException("Invalid order quantity")
        rows = db.session.scalars(
            select(VariantStock)
            .where(VariantStock.id.in_(sorted(quantities)))
            .order_by(VariantStock.id)
            .with_for_update(of=VariantStock)
            .execution_options(populate_existing=True)
        ).all()
        if len(rows) != len(quantities):
            raise ResourceNotFoundException("Variant stock not found")
        for stock in rows:
            if not restore:
                if stock.is_deleted:
                    raise BadRequestException("Variant stock unavailable")
                variant = db.session.get(Variant, stock.variant_id, populate_existing=True)
                if variant is None or variant.is_deleted or not variant.is_active:
                    raise BadRequestException("Variant unavailable")
                product = db.session.get(Product, variant.product_id, populate_existing=True)
                if product is None or product.is_deleted or not product.is_active:
                    raise BadRequestException("Product unavailable")
                if stock.unit_id != product.unit_id:
                    raise BadRequestException("Stock unit must match the product base unit")
                base = db.session.scalar(select(ProductUnit).where(
                    ProductUnit.product_id == product.id,
                    ProductUnit.unit_id == stock.unit_id,
                    ProductUnit.is_deleted.is_(False),
                ).execution_options(populate_existing=True))
                unit = db.session.get(Unit, stock.unit_id, populate_existing=True)
                if (base is None or base.multiplier != Decimal("1")
                        or unit is None or unit.is_deleted or not unit.is_active):
                    raise BadRequestException("Stock base unit is not configured")
            after = stock.qty + quantities[stock.id] if restore else stock.qty - quantities[stock.id]
            if after < 0:
                raise BadRequestException("Insufficient stock")
            if after > MAX_QTY:
                raise BadRequestException("Stock quantity exceeds allowed limit")
        return rows

    def _change_order_stock(self, quantities, restore, order_id, order_code, user_id):
        rows = self.lock_order_stocks(quantities, restore=restore)
        for stock in rows:
            quantity = quantities[stock.id]
            before = stock.qty
            stock.qty = before + quantity if restore else before - quantity
            stock.updated_at = DateUtil.now()
            stock.update_uid = user_id
            db.session.add(StockMovement(
                variant_stock_id=stock.id, unit_id=stock.unit_id,
                type="IN" if restore else "OUT", qty_change=quantity,
                base_qty_change=quantity, multiplier=Decimal("1"),
                qty_before=before, qty_after=stock.qty,
                reference_type="ORDER_RETURN" if restore else "ORDER",
                reference_id=order_id,
                note=("Order cancellation: " if restore else "Website order checkout: ") + str(order_code),
                created_at=DateUtil.now(), create_uid=user_id,
            ))
        db.session.flush()

    def change_order_stock(self, quantities, restore, order_id, order_code, *, commit=True, user_id=None):
        """Keep standalone behavior; commit=False leaves ALL transaction control to caller.

        On failure in caller-owned mode the caller must roll back the transaction.
        No gateway calls should run while these stock locks are held.
        """
        if not commit:
            return self._change_order_stock(quantities, restore, order_id, order_code, user_id)
        try:
            self._change_order_stock(quantities, restore, order_id, order_code, user_id)
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
