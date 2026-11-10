
from sqlalchemy import select

from app.extensions import db
from app.models.variant_stock import VariantStock
from app.models.variant import Variant
from app.models.product import Product
from app.models.color import Color
from app.models.size import Size
from app.repositories.stock_movement_repository import (
    StockMovementRepository
)
from app.schemas.stock_movement_schema import (
    StockMovementResponseSchema
)


class StockMovementService:

    def __init__(self):
        self.repository = StockMovementRepository()
        self.schema = StockMovementResponseSchema()

    # Paginated history with product and variant details
    def get_paginated(self, filters, params=None):
        result = self.repository.find_paginated(
            filters, params
        )

        movements = result["items"]
        stock_ids = {
            movement.variant_stock_id
            for movement in movements
        }

        details = {}

        if stock_ids:
            rows = db.session.execute(
                select(
                    VariantStock.id,
                    Product.code,
                    Product.name,
                    Variant.sku_prefix,
                    Color.name,
                    Size.value,
                )
                .select_from(VariantStock)
                .join(
                    Variant,
                    Variant.id == VariantStock.variant_id
                )
                .join(
                    Product,
                    Product.id == Variant.product_id
                )
                .outerjoin(
                    Color,
                    Color.id == Variant.color_id
                )
                .outerjoin(
                    Size,
                    Size.id == VariantStock.size_id
                )
                .where(VariantStock.id.in_(stock_ids))
            ).all()

            for row in rows:
                details[row[0]] = {
                    "product_code": row[1],
                    "product_name": row[2],
                    "sku_prefix": row[3],
                    "color_name": row[4],
                    "size": row[5],
                }

        items = []

        for movement in movements:
            item = self.schema.dump(movement)

            item.update(
                details.get(
                    movement.variant_stock_id,
                    {
                        "product_code": None,
                        "product_name": None,
                        "sku_prefix": None,
                        "color_name": None,
                        "size": None,
                    }
                )
            )

            items.append(item)

        return {
            **result,
            "items": items,
        }
