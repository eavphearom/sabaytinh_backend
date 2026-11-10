
from sqlalchemy import or_

from app.models.size import Size
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil


class SizeRepository(BaseRepository):

    def __init__(self):
        super().__init__(Size)

    # Get sizes with search, filter and pagination
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
                    Size.name.ilike(pattern, escape="\\"),
                    Size.value.ilike(pattern, escape="\\"),
                    Size.size_system.ilike(pattern, escape="\\"),
                )
            )

        return PaginationUtil.paginate(
            query=query,
            model=Size,
            filters=filters,
            allowed_sort_fields={
                "id", "name", "value",
                "size_system", "created_at", "is_active"
            }
        )
