
from sqlalchemy import or_
from app.extensions import db

from app.models.banner import Banner
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil


class BannerRepository(BaseRepository):

    def __init__(self):
        super().__init__(Banner)

    def find_active_for_home(self):
        return db.session.scalars(self._query().where(Banner.is_active.is_(True))
                                  .order_by(Banner.id.asc())).all()

    # Pagination with search
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
                    Banner.title.ilike(pattern, escape="\\"),
                    Banner.subtitle.ilike(pattern, escape="\\")
                )
            )

        return PaginationUtil.paginate(
            query=query,
            model=Banner,
            filters=filters,
            allowed_sort_fields={
                "id",
                "title",
                "created_at",
                "is_active"
            }
        )
