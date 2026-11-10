
from sqlalchemy import (
    BigInteger,
    String,
    Text,
    Boolean,
    ForeignKey,
    Identity,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin


class Product(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "products"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
    )

    # Foreign keys
    category_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("categories.id"),
        nullable=False,
    )

    brand_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("brands.id"),
        nullable=False,
    )

    unit_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("units.id"),
        nullable=False,
    )

    # Product information
    code: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )

    name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    slug: Mapped[str] = mapped_column(
        String(200),
        unique=True,
        nullable=False,
    )

    description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default="true",
        nullable=False,
    )

    # Relationships
    category = relationship("Category")
    brand = relationship("Brand")
    unit = relationship("Unit")
