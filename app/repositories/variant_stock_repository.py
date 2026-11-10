from sqlalchemy import select
from app.extensions import db
from app.common.base_repository import BaseRepository
from app.models.variant_stock import VariantStock
class VariantStockRepository(BaseRepository):
    def __init__(self): super().__init__(VariantStock)
    def by_variant(self, variant_id):
        return db.session.scalars(select(VariantStock).where(VariantStock.variant_id == variant_id, VariantStock.is_deleted.is_(False)).order_by(VariantStock.id)).all()
    def for_update(self, stock_id):
        return db.session.scalar(select(VariantStock).where(VariantStock.id == stock_id, VariantStock.is_deleted.is_(False)).with_for_update())
