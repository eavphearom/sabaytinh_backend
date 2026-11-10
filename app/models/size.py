
from sqlalchemy import BigInteger, String, Boolean, Text, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Size(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "sizes"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    name: Mapped[str | None] = mapped_column(String(50))
    value: Mapped[str | None] = mapped_column(String(30))
    size_system: Mapped[str | None] = mapped_column(
        String(20), default="INT", nullable=True
    )
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
