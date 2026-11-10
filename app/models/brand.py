
from sqlalchemy import BigInteger, String, Boolean, Text, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Brand(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "brands"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(120), nullable=False
    )

    slug: Mapped[str] = mapped_column(
        String(150), unique=True, nullable=False
    )

    logo: Mapped[str | None] = mapped_column(String(500))
    description: Mapped[str | None] = mapped_column(Text)

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
