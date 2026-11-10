
from datetime import date, timedelta

from sqlalchemy import select, or_

from app.models.stock_movement import StockMovement
from app.models.variant_stock import VariantStock
from app.models.variant import Variant
from app.models.product import Product
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil
from app.exceptions.api_exception import BadRequestException


class StockMovementRepository(BaseRepository):

    def __init__(self):
        super().__init__(StockMovement)

    @staticmethod
    def _parse_id(params, key):
        value = params.get(key)

        if value is None or value == "":
            return None

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            raise BadRequestException(f"Invalid {key}")

        if parsed <= 0:
            raise BadRequestException(f"Invalid {key}")

        return parsed

    @staticmethod
    def _parse_date(params, key):
        value = params.get(key)

        if value is None or value == "":
            return None

        try:
            if (
                len(value) != 10
                or date.fromisoformat(value).isoformat() != value
            ):
                raise ValueError

            return date.fromisoformat(value)

        except ValueError:
            raise BadRequestException(
                f"{key} must be a valid date in YYYY-MM-DD format"
            )

    # Pagination, search, and filtering
    def find_paginated(self, filters, params=None):
        params = params or {}

        query = self._query(filters.include_deleted)

        # Search by product or variant SKU prefix.
        # Do not exclude archived catalog records from history.
        if filters.search:
            keyword = (
                filters.search.strip()
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )

            pattern = f"%{keyword}%"

            matching_stock_ids = (
                select(VariantStock.id)
                .join(
                    Variant,
                    Variant.id == VariantStock.variant_id
                )
                .join(
                    Product,
                    Product.id == Variant.product_id
                )
                .where(
                    or_(
                        Product.code.ilike(pattern, escape="\\"),
                        Product.name.ilike(pattern, escape="\\"),
                        Variant.sku_prefix.ilike(
                            pattern, escape="\\"
                        ),
                    )
                )
            )

            query = query.where(
                StockMovement.variant_stock_id.in_(
                    matching_stock_ids
                )
            )

        # Filter by related IDs
        for key, column in (
            ("variant_stock_id", StockMovement.variant_stock_id),
            ("unit_id", StockMovement.unit_id),
            ("reference_id", StockMovement.reference_id),
        ):
            value = self._parse_id(params, key)

            if value is not None:
                query = query.where(column == value)

        # Movement direction
        movement_type = params.get("type")

        if movement_type:
            movement_type = movement_type.strip().upper()

            if movement_type not in ("IN", "OUT"):
                raise BadRequestException(
                    "type must be IN or OUT"
                )

            query = query.where(
                StockMovement.type == movement_type
            )

        # Business reference
        reference_type = params.get("reference_type")

        if reference_type:
            from app.enums.stock_reference_type import (
                StockReferenceType
            )

            reference_type = reference_type.strip().upper()

            if reference_type not in {
                item.value for item in StockReferenceType
            }:
                raise BadRequestException(
                    "Invalid reference_type"
                )

            query = query.where(
                StockMovement.reference_type == reference_type
            )

        # Cambodia-local date filters
        date_from = self._parse_date(params, "date_from")
        date_to = self._parse_date(params, "date_to")

        if date_from and date_to and date_from > date_to:
            raise BadRequestException(
                "date_from must be on or before date_to"
            )

        if date_from:
            query = query.where(
                StockMovement.created_at >= date_from
            )

        if date_to:
            query = query.where(
                StockMovement.created_at
                < date_to + timedelta(days=1)
            )

        return PaginationUtil.paginate(
            query=query,
            model=StockMovement,
            filters=filters,
            allowed_sort_fields={
                "id", "created_at", "type"
            }
        )
