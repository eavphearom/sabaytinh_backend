from sqlalchemy import BigInteger, CheckConstraint, ForeignKey, Identity, Integer, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin

class VariantStock(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "variant_stocks"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    variant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("variants.id"), nullable=False)
    size_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("sizes.id"), nullable=False)
    unit_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("units.id"), nullable=False)
    sku: Mapped[str] = mapped_column(String(100), nullable=False)
    qty: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    low_stock_alert: Mapped[int] = mapped_column(Integer, nullable=False, default=0, server_default="0")
    variant = relationship("Variant")
    size = relationship("Size")
    unit = relationship("Unit")
    __table_args__ = (
        UniqueConstraint("variant_id", "size_id", name="uq_variant_stock_size"),
        CheckConstraint("qty >= 0", name="chk_variant_stock_qty"),
        CheckConstraint("low_stock_alert >= 0", name="chk_variant_low_stock_alert"),
    )
