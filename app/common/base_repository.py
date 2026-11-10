
from datetime import datetime, timezone

from sqlalchemy import select, func

from app.extensions import db
from app.utils.date_util import DateUtil


class BaseRepository:
    def __init__(self, model):
        self.model = model

    def _query(self, include_deleted=False):
        query = select(self.model)

        if (
            hasattr(self.model, "is_deleted")
            and not include_deleted
        ):
            query = query.where(
                self.model.is_deleted.is_(False)
            )

        return query

    def find_by_id(self, id, include_deleted=False):
        query = self._query(include_deleted).where(
            self.model.id == id
        )
        return db.session.scalar(query)

    def find_all(self, include_deleted=False):
        query = self._query(include_deleted).order_by(
            self.model.id.asc()
        )
        return db.session.scalars(query).all()

    def exists_by_id(self, id, include_deleted=False):
        query = self._query(include_deleted).where(
            self.model.id == id
        ).exists()

        return bool(
            db.session.scalar(select(query))
        )

    def paginate(
        self,
        page_no=1,
        per_page=10,
        include_deleted=False
    ):
        if page_no < 1 or not 1 <= per_page <= 100:
            raise ValueError("Invalid pagination parameters")

        query = self._query(include_deleted)

        total = db.session.scalar(
            select(func.count()).select_from(
                query.order_by(None).subquery()
            )
        ) or 0

        items = db.session.scalars(
            query.order_by(self.model.id.asc())
            .offset((page_no - 1) * per_page)
            .limit(per_page)
        ).all()

        return {
            "items": items,
            "pagination": {
                "per_page": per_page,
                "total": total,
                "total_page": (total + per_page - 1) // per_page,
                "page_no": page_no,
            },
        }

    def soft_delete_by_id(
        self,
        id,
        deleted_uid=None,
        reason=None
    ):
        entity = self.find_by_id(id)

        if entity is None:
            return False

        if not hasattr(entity, "is_deleted"):
            raise ValueError(
                "This model does not support soft delete"
            )

        entity.is_deleted = True
        entity.deleted_at = DateUtil.now()
        entity.deleted_uid = deleted_uid
        entity.deleted_reason = reason

        db.session.flush()
        return True
