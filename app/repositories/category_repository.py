
from sqlalchemy import select, or_

from app.extensions import db
from app.models.category import Category
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil


class CategoryRepository(BaseRepository):

    def __init__(self):
        super().__init__(Category)

    def find_by_slug(self, slug):
        # Check all records because slug is globally unique.
        return db.session.scalar(
            select(Category).where(Category.slug == slug)
        )

    def find_paginated(self, filters):
        query = self._query(filters.include_deleted)

        if filters.search:
            # Escape LIKE wildcards in user searches.
            keyword = (
                filters.search
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{keyword}%"

            query = query.where(
                or_(
                    Category.name.ilike(pattern, escape="\\"),
                    Category.slug.ilike(pattern, escape="\\")
                )
            )

        return PaginationUtil.paginate(
            query=query,
            model=Category,
            filters=filters,
            allowed_sort_fields={
                "id", "name", "created_at", "is_active"
            }
        )
