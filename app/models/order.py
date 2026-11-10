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
    Index,
    Numeric,
    PrimaryKeyConstraint,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import AuditSoftDeleteMixin
from app.enums.currency import Currency
from app.enums.order_status import OrderStatus
from app.enums.payment_status import PaymentStatus
from app.extensions import db
from app.utils.date_util import DateUtil


class Order(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "orders"

    id: Mapped[int] = mapped_column(
        BigInteger,
        Identity(),
        primary_key=True,
        nullable=False,
    )

    order_code: Mapped[str] = mapped_column(
        String(100),
        nullable=False,
    )

    customer_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_orders_customer",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    delivery_method_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey(
            "delivery_methods.id",
            name="fk_orders_delivery_method",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    delivery_method_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    order_status: Mapped[OrderStatus] = mapped_column(
        SQLAlchemyEnum(
            OrderStatus,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
        default=OrderStatus.PENDING.value,
        server_default=text("'PENDING'::character varying"),
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

    recipient_name: Mapped[str] = mapped_column(
        String(150),
        nullable=False,
    )

    recipient_phone: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    delivery_address: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    cancelled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )

    delivered_at: Mapped[datetime | None] = mapped_column(
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

    customer = relationship(
        "User"
    )

    delivery_method = relationship(
        "DeliveryMethod"
    )

    items = relationship(
        "OrderItem", back_populates="order", passive_deletes="all"
    )

    payments = relationship(
        "Payment", back_populates="order", passive_deletes="all"
    )

    invoice = relationship(
        "Invoice", back_populates="order", uselist=False, passive_deletes="all"
    )

    status_histories = relationship(
        "OrderStatusHistory", back_populates="order", passive_deletes="all"
    )

    __table_args__ = (
        PrimaryKeyConstraint('id', name="orders_pkey"),
        UniqueConstraint('order_code', name="orders_order_code_key"),
        CheckConstraint(
            'subtotal >= 0::numeric',
            name="chk_orders_subtotal",
        ),
        CheckConstraint(
            'shipping_fee >= 0::numeric',
            name="chk_orders_shipping_fee",
        ),
        CheckConstraint(
            'discount_amount >= 0::numeric',
            name="chk_orders_discount",
        ),
        CheckConstraint(
            'total_amount >= 0::numeric',
            name="chk_orders_total",
        ),
        Index(
            "idx_orders_created_at",
            "created_at",
        ),
        Index(
            "idx_orders_customer_id",
            "customer_id",
        ),
        Index(
            "idx_orders_order_status",
            "order_status",
        ),
        Index(
            "idx_orders_payment_status",
            "payment_status",
        ),
    )
