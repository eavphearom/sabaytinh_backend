from sqlalchemy import select
from app.extensions import db
from app.common.base_repository import BaseRepository
from app.models.variant import Variant
class VariantRepository(BaseRepository):
    def __init__(self): super().__init__(Variant)
    def by_product(self, product_id):
        return db.session.scalars(select(Variant).where(Variant.product_id == product_id, Variant.is_deleted.is_(False)).order_by(Variant.id)).all()
    def by_product_color(self, product_id,color_id):
        return db.session.scalar(select(Variant).where(Variant.product_id == product_id, Variant.color_id == color_id))
