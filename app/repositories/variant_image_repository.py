from sqlalchemy import select
from app.extensions import db
from app.common.base_repository import BaseRepository
from app.models.variant_image import VariantImage
class VariantImageRepository(BaseRepository):
    def __init__(self): super().__init__(VariantImage)
    def by_variant(self, variant_id):
        return db.session.scalars(select(VariantImage).where(VariantImage.variant_id == variant_id, VariantImage.is_deleted.is_(False)).order_by(VariantImage.id)).all()
