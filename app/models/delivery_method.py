from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Identity,
    Integer,
    Numeric,
    String,
    text,
)
from app.enums.currency import Currency
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class DeliveryMethod(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "delivery_methods"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True
    )

    name: Mapped[str] = mapped_column(
        String(120),
        nullable=False
    )

    code: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        unique=True
    )

    fee: Mapped[Decimal] = mapped_column(
        Numeric(10, 5),
        nullable=False,
        default=Decimal("0"),
        server_default="0"
    )

    currency: Mapped[str] = mapped_column(
        String(10),
        nullable=False,
        default=Currency.USD.value,
        server_default=Currency.USD.value
    )

    estimated_min_days: Mapped[int | None] = mapped_column(
        Integer
    )

    estimated_max_days: Mapped[int | None] = mapped_column(
        Integer
    )

    logo: Mapped[str | None] = mapped_column(
        String(500)
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("true")
    )

    __table_args__ = (
        CheckConstraint(
            "fee >= 0",
            name="chk_delivery_fee"
        ),
        CheckConstraint(
            "(estimated_min_days IS NULL OR estimated_min_days >= 0) "
            "AND (estimated_max_days IS NULL OR estimated_max_days >= 0) "
            "AND (estimated_min_days IS NULL "
            "OR estimated_max_days IS NULL "
            "OR estimated_min_days <= estimated_max_days)",
            name="chk_delivery_estimated_days"
        ),
    )