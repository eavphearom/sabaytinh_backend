
from sqlalchemy import BigInteger, String, Boolean, Identity
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Role(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    code: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False
    )
    description: Mapped[str | None] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )

    users: Mapped[list["User"]] = relationship(
        "User", back_populates="role"
    )
