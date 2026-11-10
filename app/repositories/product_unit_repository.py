
from sqlalchemy import select

from app.extensions import db
from app.models.product_unit import ProductUnit
from app.common.base_repository import BaseRepository


class ProductUnitRepository(BaseRepository):

    def __init__(self):
        super().__init__(ProductUnit)

    # Find active product-unit configuration
    def find_by_product_and_unit(self, product_id, unit_id):
        return db.session.scalar(
            select(ProductUnit).where(
                ProductUnit.product_id == product_id,
                ProductUnit.unit_id == unit_id,
                ProductUnit.is_deleted.is_(False)
            )
        )

    # Find all active units configured for a product
    def find_by_product(self, product_id):
        return db.session.scalars(
            select(ProductUnit)
            .where(
                ProductUnit.product_id == product_id,
                ProductUnit.is_deleted.is_(False)
            )
            .order_by(ProductUnit.id)
        ).all()
