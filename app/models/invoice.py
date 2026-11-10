from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Identity,
    Numeric,
    PrimaryKeyConstraint,
    String,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import AuditSoftDeleteMixin
from app.enums.currency import Currency
from app.enums.payment_status import PaymentStatus
from app.extensions import db
from app.utils.date_util import DateUtil


class Invoice(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "invoices"

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
            name="fk_invoices_order",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    invoice_no: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    subtotal: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text('0'),
    )

    shipping_fee: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text('0'),
    )

    discount_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text('0'),
    )

    total_amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
        default=Decimal("0"),
        server_default=text('0'),
    )

    currency: Mapped[Currency] = mapped_column(
        SQLAlchemyEnum(
            Currency,
            native_enum=False,
            create_constraint=False,
            length=3,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=Currency.USD.value,
        server_default=text("'USD'::character varying"),
    )

    payment_status: Mapped[PaymentStatus] = mapped_column(
        SQLAlchemyEnum(
            PaymentStatus,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=PaymentStatus.PENDING.value,
        server_default=text("'PENDING'::character varying"),
    )

    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text('CURRENT_TIMESTAMP'),
    )

    paid_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
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
        "Order", back_populates="invoice"
    )

    __table_args__ = (
        PrimaryKeyConstraint('id', name="invoices_pkey"),
        UniqueConstraint('invoice_no', name="invoices_invoice_no_key"),
        UniqueConstraint('order_id', name="invoices_order_id_key"),
        CheckConstraint(
            'subtotal >= 0::numeric',
            name="chk_invoices_subtotal",
        ),
        CheckConstraint(
            'shipping_fee >= 0::numeric',
            name="chk_invoices_shipping_fee",
        ),
        CheckConstraint(
            'discount_amount >= 0::numeric',
            name="chk_invoices_discount",
        ),
        CheckConstraint(
            'total_amount >= 0::numeric',
            name="chk_invoices_total",
        ),
    )
