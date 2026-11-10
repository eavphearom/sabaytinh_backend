
from sqlalchemy import BigInteger, String, Boolean, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Color(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "colors"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(100), nullable=False
    )

    hex_code: Mapped[str | None] = mapped_column(String(50))

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
