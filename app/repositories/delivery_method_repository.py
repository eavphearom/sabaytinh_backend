from sqlalchemy import func, or_, select

from app.common.base_repository import BaseRepository
from app.extensions import db
from app.models.delivery_method import DeliveryMethod


class DeliveryMethodRepository(BaseRepository):

    def __init__(self):
        super().__init__(DeliveryMethod)

    def find_active_by_id(self, method_id):
        return db.session.scalar(
            select(DeliveryMethod).where(
                DeliveryMethod.id == method_id,
                DeliveryMethod.is_deleted.is_(False),
                DeliveryMethod.is_active.is_(True)
            )
        )

    def code_exists(self, code, exclude_id=None):
        query = select(DeliveryMethod.id).where(
            DeliveryMethod.code == code
        )

        if exclude_id is not None:
            query = query.where(
                DeliveryMethod.id != exclude_id
            )

        return db.session.scalar(query.limit(1)) is not None

    def paginate(
        self,
        page,
        page_size,
        search=None,
        active_only=False
    ):
        conditions = [
            DeliveryMethod.is_deleted.is_(False)
        ]

        if active_only:
            conditions.append(
                DeliveryMethod.is_active.is_(True)
            )

        if search:
            pattern = f"%{search.strip()}%"

            conditions.append(
                or_(
                    DeliveryMethod.name.ilike(pattern),
                    DeliveryMethod.code.ilike(pattern)
                )
            )

        total = db.session.scalar(
            select(func.count())
            .select_from(DeliveryMethod)
            .where(*conditions)
        ) or 0

        rows = db.session.scalars(
            select(DeliveryMethod)
            .where(*conditions)
            .order_by(DeliveryMethod.id.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        ).all()

        return rows, total