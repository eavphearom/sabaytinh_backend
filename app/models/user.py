
from sqlalchemy import BigInteger, String, ForeignKey, Identity
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class User(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(
        BigInteger, Identity(), primary_key=True
    )

    username: Mapped[str] = mapped_column(
        String(100), nullable=False
    )
    email: Mapped[str] = mapped_column(
        String(150), nullable=False
    )
    password: Mapped[str] = mapped_column(
        String(255), nullable=False
    )
    phone: Mapped[str | None] = mapped_column(String(30))
    profile: Mapped[str | None] = mapped_column(String(500))

    role_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(50), default="ACTIVE", nullable=False
    )

    role: Mapped["Role"] = relationship(
        "Role", back_populates="users"
    )

    auth_providers: Mapped[list["UserAuthProvider"]] = relationship(
        "UserAuthProvider", back_populates="user"
    )

    refresh_sessions: Mapped[list["RefreshSession"]] = relationship(
        "RefreshSession", back_populates="user"
    )
