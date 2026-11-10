
from sqlalchemy import (
    BigInteger, String, ForeignKey, Identity,
    Index, text
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class UserAuthProvider(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "user_auth_providers"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    user_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("users.id"),
        nullable=False
    )

    provider: Mapped[str] = mapped_column(
        String(30), nullable=False
    )

    provider_user_id: Mapped[str] = mapped_column(
        String(255), nullable=False
    )

    user: Mapped["User"] = relationship(
        "User", back_populates="auth_providers"
    )

    __table_args__ = (
        Index(
            "uq_auth_provider_account",
            "provider",
            "provider_user_id",
            unique=True,
            postgresql_where=text("is_deleted = FALSE")
        ),
        Index(
            "uq_auth_user_provider",
            "user_id",
            "provider",
            unique=True,
            postgresql_where=text("is_deleted = FALSE")
        ),
    )
