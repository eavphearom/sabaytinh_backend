
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    ForeignKey,
    Identity,
    Numeric,
    CheckConstraint,
    Index,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class ProductUnit(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "product_units"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("products.id"),
        nullable=False
    )

    unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("units.id"),
        nullable=False
    )

    multiplier: Mapped[Decimal] = mapped_column(
        Numeric(10, 5),
        nullable=False,
        default=Decimal("1.00000"),
        server_default="1"
    )

    product = relationship("Product")
    unit = relationship("Unit")

    __table_args__ = (
        CheckConstraint(
            "multiplier > 0",
            name="ck_product_units_multiplier_positive"
        ),
        Index(
            "uq_product_units_active_product_unit",
            "product_id",
            "unit_id",
            unique=True,
            postgresql_where=text("is_deleted = false")
        ),
    )
