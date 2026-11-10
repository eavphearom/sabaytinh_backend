from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Identity,
    Index,
    Integer,
    Numeric,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import AuditSoftDeleteMixin
from app.extensions import db
from app.utils.date_util import DateUtil


class OrderItem(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
        nullable=False,
    )

    order_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "orders.id",
            name="fk_order_items_order",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    product_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "products.id",
            name="fk_order_items_product",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    variant_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "variants.id",
            name="fk_order_items_variant",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    variant_stock_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "variant_stocks.id",
            name="fk_order_items_variant_stock",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    product_code: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    product_name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    sku: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    color_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    size_name: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    image: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
    )

    quantity: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    unit_price: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
    )

    # These audit column definitions differ from the shared mixin.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        default=DateUtil.now,
        server_default=text('CURRENT_TIMESTAMP'),
    )

    # Match the SQL server default without changing the shared audit mixin.
    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text('false'),
    )

    deleted_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    order = relationship(
        "Order", back_populates="items"
    )

    product = relationship(
        "Product"
    )

    variant = relationship(
        "Variant"
    )

    variant_stock = relationship(
        "VariantStock"
    )

    __table_args__ = (
        PrimaryKeyConstraint('id', name="order_items_pkey"),
        CheckConstraint(
            'quantity > 0',
            name="chk_order_items_quantity",
        ),
        CheckConstraint(
            'unit_price >= 0::numeric',
            name="chk_order_items_unit_price",
        ),
        CheckConstraint(
            'subtotal >= 0::numeric',
            name="chk_order_items_subtotal",
        ),
        Index(
            "idx_order_items_order_id",
            "order_id",
        ),
        Index(
            "idx_order_items_product_id",
            "product_id",
        ),
        Index(
            "idx_order_items_variant_stock_id",
            "variant_stock_id",
        ),
    )
