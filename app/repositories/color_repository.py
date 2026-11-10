
from sqlalchemy import or_

from app.models.color import Color
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil


class ColorRepository(BaseRepository):

    def __init__(self):
        super().__init__(Color)

    # Pagination with optional search
    def find_paginated(self, filters):
        query = self._query(filters.include_deleted)

        if filters.search:
            keyword = (
                filters.search
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{keyword}%"

            query = query.where(
                or_(
                    Color.name.ilike(pattern, escape="\\"),
                    Color.hex_code.ilike(pattern, escape="\\")
                )
            )

        return PaginationUtil.paginate(
            query=query,
            model=Color,
            filters=filters,
            allowed_sort_fields={
                "id", "name", "created_at", "is_active"
            }
        )
