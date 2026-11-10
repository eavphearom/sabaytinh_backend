
from decimal import Decimal

from sqlalchemy import BigInteger, String, Boolean, Numeric, Identity
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Unit(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "units"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True
    )

    code: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
        unique=True
    )

    name: Mapped[str] = mapped_column(
        String(100),
        nullable=False
    )

    multiplier: Mapped[Decimal] = mapped_column(
        Numeric(10, 5),
        nullable=False,
        default=Decimal("1.00000"),
        server_default="1"
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true"
    )
