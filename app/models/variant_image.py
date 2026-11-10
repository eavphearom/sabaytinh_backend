from sqlalchemy import BigInteger, Boolean, ForeignKey, Identity, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from app.extensions import db
from app.common.base_model import AuditSoftDeleteMixin

class VariantImage(AuditSoftDeleteMixin, db.Model):
    __tablename__ = "variant_images"
    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    variant_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("variants.id"), nullable=False)
    image: Mapped[str] = mapped_column(String(500), nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False, server_default="false")
    variant = relationship("Variant")
    __table_args__ = (Index("uq_variant_primary_image", "variant_id", unique=True,
                            postgresql_where=text("is_primary = TRUE AND is_deleted = FALSE")),)
