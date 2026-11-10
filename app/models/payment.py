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
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import AuditSoftDeleteMixin
from app.enums.currency import Currency
from app.enums.payment_method import PaymentMethod
from app.enums.payment_status import PaymentStatus
from app.extensions import db
from app.utils.date_util import DateUtil


class Payment(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "payments"

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
            name="fk_payments_order",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    payment_method: Mapped[PaymentMethod] = mapped_column(
        SQLAlchemyEnum(
            PaymentMethod,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
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

    amount: Mapped[Decimal] = mapped_column(
        Numeric(12, 2),
        nullable=False,
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

    transaction_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    payment_reference: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
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

    qr_string: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    abapay_deeplink: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    checkout_qr_url: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )

    gateway_state: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    gateway_lease_token: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    gateway_lease_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )

    next_check_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        nullable=True,
    )

    checkout_message: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    cancellation_reason: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    order = relationship(
        "Order", back_populates="payments"
    )

    __table_args__ = (
        PrimaryKeyConstraint('id', name="payments_pkey"),
        CheckConstraint(
            'amount >= 0::numeric',
            name="chk_payments_amount",
        ),
        Index(
            "idx_payments_online_reconcile",
            "next_check_at",
            "id",
            postgresql_where=text(
                "payment_method::text = 'ONLINE'::text "
                "AND payment_status::text = 'PENDING'::text "
                "AND is_deleted = false"
            ),
        ),
        Index(
            "idx_payments_order_id",
            "order_id",
        ),
        Index(
            "idx_payments_payment_status",
            "payment_status",
        ),
        Index(
            "uq_payments_transaction_id",
            "transaction_id",
            unique=True,
            postgresql_where=text('transaction_id IS NOT NULL'),
        ),
    )
