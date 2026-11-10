
from datetime import datetime, timezone

from sqlalchemy import BigInteger, Boolean, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column
from app.utils.date_util import DateUtil

class AuditSoftDeleteMixin:
    created_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        default=DateUtil.now,
        nullable=True
    )

    create_uid: Mapped[int | None] = mapped_column(BigInteger)

    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False),
        onupdate=DateUtil.now,
        nullable=True
    )

    update_uid: Mapped[int | None] = mapped_column(BigInteger)

    is_deleted: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        nullable=False
    )

    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=False)
    )

    deleted_uid: Mapped[int | None] = mapped_column(BigInteger)

    deleted_reason: Mapped[str | None] = mapped_column(
        String(500)
    )
