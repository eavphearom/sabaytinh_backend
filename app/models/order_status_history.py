from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    Enum as SQLAlchemyEnum,
    ForeignKey,
    Identity,
    Index,
    PrimaryKeyConstraint,
    String,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.common.base_model import AuditSoftDeleteMixin
from app.enums.order_status import OrderStatus
from app.extensions import db
from app.utils.date_util import DateUtil


class OrderStatusHistory(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "order_status_histories"

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
            name="fk_order_status_history_order",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
        nullable=False,
    )

    old_status: Mapped[OrderStatus | None] = mapped_column(
        SQLAlchemyEnum(
            OrderStatus,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=True,
    )

    new_status: Mapped[OrderStatus] = mapped_column(
        SQLAlchemyEnum(
            OrderStatus,
            native_enum=False,
            create_constraint=False,
            length=30,
            values_callable=lambda enum: [member.value for member in enum],
        ),
        nullable=False,
    )

    note: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
    )

    changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        nullable=False,
        server_default=text('CURRENT_TIMESTAMP'),
    )

    changed_by: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey(
            "users.id",
            name="fk_order_status_history_user",
            onupdate="NO ACTION",
            ondelete="NO ACTION",
        ),
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
        "Order", back_populates="status_histories"
    )

    changed_by_user = relationship(
        "User"
    )

    __table_args__ = (
        PrimaryKeyConstraint('id', name="order_status_histories_pkey"),
        Index(
            "idx_order_status_histories_changed_at",
            "changed_at",
        ),
        Index(
            "idx_order_status_histories_order_id",
            "order_id",
        ),
    )
