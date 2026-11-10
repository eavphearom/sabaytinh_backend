from decimal import Decimal
from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Index, Integer, Numeric, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin

class StockMovement(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "stock_movements"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    variant_stock_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("variant_stocks.id"), nullable=False)
    unit_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("units.id"), nullable=True)
    type: Mapped[str] = mapped_column(String(30), nullable=False)
    qty_change: Mapped[int] = mapped_column(Integer, nullable=False)
    multiplier: Mapped[Decimal] = mapped_column(Numeric(10, 5), nullable=False, default=Decimal("1"), server_default="1")
    base_qty_change: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_before: Mapped[int] = mapped_column(Integer, nullable=False)
    qty_after: Mapped[int] = mapped_column(Integer, nullable=False)
    reference_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    reference_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    stock = relationship("VariantStock")
    unit = relationship("Unit")
    __table_args__ = (
        CheckConstraint("qty_before >= 0", name="chk_stock_movement_qty_before"),
        CheckConstraint("qty_after >= 0", name="chk_stock_movement_qty_after"),
        CheckConstraint("qty_change >= 0", name="chk_stock_movement_change"),
        CheckConstraint("(type = 'IN' AND qty_after = qty_before + base_qty_change) OR (type = 'OUT' AND qty_after = qty_before - base_qty_change)", name="chk_stock_movement_balance"),
        CheckConstraint("type IN ('IN', 'OUT')", name="chk_stock_movement_type"),
        Index("idx_stock_movements_variant_stock", "variant_stock_id", text("created_at DESC")),
    )
