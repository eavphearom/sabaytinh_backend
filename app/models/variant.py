from decimal import Decimal
from sqlalchemy import BigInteger, Boolean, CheckConstraint, ForeignKey, Identity, Index, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin

class Variant(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "variants"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    product_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("products.id"), nullable=False)
    color_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("colors.id"), nullable=False)
    sku_prefix: Mapped[str] = mapped_column(String(100), nullable=False)
    cost: Mapped[Decimal] = mapped_column(Numeric(15, 5), nullable=False, default=Decimal("0"), server_default="0")
    price: Mapped[Decimal] = mapped_column(Numeric(15, 5), nullable=False, default=Decimal("0"), server_default="0")
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, server_default="true")
    product = relationship("Product")
    color = relationship("Color")
    __table_args__ = (
        CheckConstraint("cost >= 0", name="chk_cost"),
        CheckConstraint("price >= 0", name="chk_price"),
        UniqueConstraint("product_id", "color_id", name="uq_variant_product_color"),
        Index("uq_product_default_variant", "product_id", unique=True,
              postgresql_where=text("is_default = TRUE AND is_deleted = FALSE")),
    )
