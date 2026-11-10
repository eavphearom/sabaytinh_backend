
from sqlalchemy import select, func, or_

from app.extensions import db
from app.models.user import User
from app.common.base_repository import BaseRepository


class UserRepository(BaseRepository):

    def __init__(self):
        super().__init__(User)

    def find_by_email(self, email: str):
        statement = (
            select(User)
            .where(
                func.lower(User.email) == email.lower(),
                User.is_deleted.is_(False)
            )
        )

        return db.session.scalar(statement)


    def role_id_exists(self, role_id):
        from app.models.role import Role
        return db.session.scalar(select(Role.id).where(
            Role.id == role_id, Role.is_deleted.is_(False)).limit(1)) is not None

    def find_admin_paginated(self, page, size, search="", role_id=None):
        from app.models.role import Role
        query = select(User.id, User.username, User.email, Role.code.label("role"),
            (User.status == "ACTIVE").label("is_active")
        ).join(Role, Role.id == User.role_id).where(User.is_deleted.is_(False))
        if search:
            keyword = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(or_(User.username.ilike(f"%{keyword}%", escape="\\"),
                User.email.ilike(f"%{keyword}%", escape="\\")))
        if role_id is not None:
            query = query.where(User.role_id == role_id)
        total = db.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.session.execute(query.order_by(User.created_at.desc().nulls_last(), User.id.desc())
            .offset((page - 1) * size).limit(size)).mappings().all()
        return dict(items=rows, total=total, per_page=size, page_no=page,
            total_page=(total + size - 1) // size)
