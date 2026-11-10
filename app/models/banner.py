
from sqlalchemy import BigInteger, String, Boolean, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Banner(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "banners"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    title: Mapped[str] = mapped_column(
        String(150), nullable=False
    )

    subtitle: Mapped[str | None] = mapped_column(
        String(255), nullable=True
    )

    image: Mapped[str] = mapped_column(
        String(500), nullable=False
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False
    )
