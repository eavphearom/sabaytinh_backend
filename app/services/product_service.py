"""Unified Product create/update, based on the user's Spring Boot ProductServiceImpl.

Service owns the transaction. StockService standalone methods commit independently,
so aggregate operations write stock movements directly inside the current transaction.
"""
import logging
from decimal import Decimal

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.product import Product
from app.models.product_unit import ProductUnit
from app.models.unit import Unit
from app.models.category import Category
from app.models.brand import Brand
from app.models.color import Color
from app.models.size import Size
from app.models.variant import Variant
from app.models.variant_image import VariantImage
from app.models.variant_stock import VariantStock
from app.models.stock_movement import StockMovement
from app.repositories.product_repository import ProductRepository
from app.schemas.product_schema import ProductResponseSchema, ProductPaginationResponseSchema
from app.exceptions.api_exception import (
    BadRequestException, DuplicateException, ResourceNotFoundException
)
from app.utils.date_util import DateUtil
from app.utils.file_util import FileUtil
from app.utils.slug_util import SlugUtil
from app.enums.image_directory import ImageDirectory

logger = logging.getLogger(__name__)
MAX_QTY = 2_147_483_647


class ProductService:
    def __init__(self):
        self.repository = ProductRepository()
        self.schema = ProductResponseSchema()

    @staticmethod
    def _required_active(model, record_id, label):
        row = db.session.get(model, record_id)
        if row is None or row.is_deleted or not row.is_active:
            raise BadRequestException(f"Invalid or inactive {label}")
        return row

    def _validate_request(self, data):
        name = (data.get("name") or "").strip()
        if not name:
            raise BadRequestException("Product name is required")
        data["name"] = name
        self._required_active(Category, data["category_id"], "category")
        self._required_active(Brand, data["brand_id"], "brand")

        variants = data.get("variants") or []
        if not variants:
            raise BadRequestException("At least one variant is required")
        if sum(bool(v.get("is_default")) for v in variants) != 1:
            raise BadRequestException("Exactly one default variant is required")

        seen_colors = set()
        for variant in variants:
            color_id = variant["color_id"]
            if color_id in seen_colors:
                raise BadRequestException("Duplicate variant color")
            seen_colors.add(color_id)
            self._required_active(Color, color_id, "color")
            if not variant.get("stocks"):
                raise BadRequestException("Each variant requires at least one size")
            seen_sizes = set()
            for stock in variant["stocks"]:
                size_id = stock["size_id"]
                if size_id in seen_sizes:
                    raise BadRequestException("Duplicate size within a variant")
                seen_sizes.add(size_id)
                self._required_active(Size, size_id, "size")
                qty = stock.get("qty")
                if qty is not None and (type(qty) is not int or qty < 0 or qty > MAX_QTY):
                    raise BadRequestException("Invalid stock quantity")
                if stock.get("low_stock_alert", 0) is None:
                    stock["low_stock_alert"] = 0
            images = variant.get("images") or []
            # New images need files; for update existing images can have ID only.
            if images and sum(bool(im.get("is_primary")) for im in images) > 1:
                raise BadRequestException("Only one primary image is allowed")

    @staticmethod
    def _pair_unit():
        pair = db.session.scalar(select(Unit).where(Unit.code == "PAIR", Unit.is_active.is_(True), Unit.is_deleted.is_(False)))
        if pair is None:
            raise BadRequestException("Active PAIR unit not found")
        return pair

    @staticmethod
    def _unique_slug(name):
        base = SlugUtil.generate(name)
        if not base:
            raise BadRequestException("Invalid product name for slug")
        for index in range(1, 10001):
            slug = base if index == 1 else f"{base}-{index}"
            if len(slug) > 200:
                raise BadRequestException("Product slug is too long")
            if db.session.scalar(select(Product.id).where(Product.slug == slug)) is None:
                return slug
        raise BadRequestException("Could not generate unique product slug")

    @staticmethod
    def _stock_change(stock, target, reference_type, reference_id, note, user_id):
        # Caller must own the transaction. Lock for reliable before/after values.
        locked = db.session.scalar(select(VariantStock).where(VariantStock.id == stock.id).with_for_update())
        if locked is None or locked.is_deleted:
            raise ResourceNotFoundException("Stock not found")
        if target < 0 or target > MAX_QTY:
            raise BadRequestException("Stock quantity out of range")
        before = locked.qty
        difference = target - before
        if difference == 0:
            return
        locked.qty = target
        locked.updated_at = DateUtil.now()
        locked.update_uid = user_id
        db.session.add(StockMovement(
            variant_stock_id=locked.id,
            unit_id=locked.unit_id,
            type="IN" if difference > 0 else "OUT",
            qty_change=abs(difference),
            multiplier=Decimal("1"),
            base_qty_change=abs(difference),
            qty_before=before,
            qty_after=target,
            reference_type=reference_type,
            reference_id=reference_id,
            note=note,
            created_at=DateUtil.now(),
            create_uid=user_id,
        ))
        db.session.flush()

    @staticmethod
    def _map_image(image):
        return {
            "id": image.id,
            "variant_id": image.variant_id,
            "image": FileUtil.get_image_url(image.image),
            "is_primary": image.is_primary,
        }

    @staticmethod
    def _map_stock(stock):
        return {
            "id": stock.id,
            "variant_id": stock.variant_id,
            "size_id": stock.size_id,
            "unit_id": stock.unit_id,
            "sku": stock.sku,
            "qty": stock.qty,
            "low_stock_alert": stock.low_stock_alert,
            "stock_status": ("OUT_OF_STOCK" if stock.qty == 0 else "LOW_STOCK" if stock.qty <= stock.low_stock_alert else "IN_STOCK"),
        }

    def _map_product(self, product):
        result = self.schema.dump(product)
        variants = db.session.scalars(select(Variant).where(
            Variant.product_id == product.id, Variant.is_deleted.is_(False)
        ).order_by(Variant.is_default.desc(), Variant.id)).all()
        result["variants"] = []
        for variant in variants:
            images = db.session.scalars(select(VariantImage).where(
                VariantImage.variant_id == variant.id, VariantImage.is_deleted.is_(False)
            ).order_by(VariantImage.id)).all()
            stocks = db.session.scalars(select(VariantStock).where(
                VariantStock.variant_id == variant.id, VariantStock.is_deleted.is_(False)
            ).order_by(VariantStock.id)).all()
            result["variants"].append({
                "id": variant.id,
                "product_id": variant.product_id,
                "color_id": variant.color_id,
                "sku_prefix": variant.sku_prefix,
                "cost": str(variant.cost),
                "price": str(variant.price),
                "is_default": variant.is_default,
                "is_active": variant.is_active,
                "images": [self._map_image(x) for x in images],
                "stocks": [self._map_stock(x) for x in stocks],
            })
        return result

    def get_by_id(self, product_id):
        product = self.repository.find_by_id(product_id)
        if product is None:
            raise ResourceNotFoundException("Product not found")
        return self._map_product(product)

    def get_paginated(self, filters, params=None):
        result = self.repository.find_paginated(filters, params)
        return {**result, "items": ProductPaginationResponseSchema(many=True).dump(
            self.repository.admin_list_projection(result["items"]))}

    def get_stock_detail(self, product_id):
        if product_id < 1 or product_id > 9_223_372_036_854_775_807:
            raise ResourceNotFoundException("Product not found")
        records = self.repository.find_admin_stocks(product_id)
        if records is None:
            raise ResourceNotFoundException("Product not found")
        product, variants, stocks, images = records
        by_variant, image_by_variant = {}, {}
        for stock in stocks:
            by_variant.setdefault(stock.variant_id, []).append(stock)
        for image in images:
            image_by_variant.setdefault(image.variant_id, FileUtil.get_image_url(image.image))

        def summary(rows):
            return dict(total_stock=sum(s.qty for s in rows), total_sizes=len(rows),
                available_sizes=sum(s.qty > 0 for s in rows),
                low_stock_sizes=sum(0 < s.qty <= s.low_stock_alert for s in rows),
                out_of_stock_sizes=sum(s.qty == 0 for s in rows))

        result = self.schema.dump(product)
        result.update(category_name=product.category.name if product.category else None,
            brand_name=product.brand.name if product.brand else None,
            total_variants=len(variants),
            image=next((image_by_variant[v.id] for v in variants if v.id in image_by_variant), None),
            **summary(stocks))
        result["variants"] = []
        for variant in variants:
            rows = by_variant.get(variant.id, [])
            result["variants"].append(dict(id=variant.id, product_id=variant.product_id,
                color_id=variant.color_id, color_name=variant.color.name if variant.color else None,
                color_hex=variant.color.hex_code if variant.color else None,
                sku_prefix=variant.sku_prefix, price=str(variant.price), cost=str(variant.cost),
                is_default=variant.is_default, is_active=variant.is_active,
                image=image_by_variant.get(variant.id), **summary(rows),
                stocks=[{**self._map_stock(s), "size_name": s.size.name if s.size else None,
                    "size_value": s.size.value if s.size else None,
                    "size": (s.size.value or s.size.name) if s.size else None} for s in rows]))
        return result

    @staticmethod
    def _clean_files(uploaded, old):
        for path in uploaded:
            try:
                FileUtil.delete_image(path)
            except OSError:
                logger.exception("Could not clean up uploaded image %s", path)
        # 'old' files never get deleted during rollback.

    @staticmethod
    def _remove_old_files(paths):
        for path in set(paths):
            try:
                FileUtil.delete_image(path)
            except OSError:
                logger.exception("Could not remove old image %s", path)

    @staticmethod
    def _set_image_primary(variant_id, selected_id):
        # Two-phase update avoids the partial UNIQUE index conflict.
        existing = db.session.scalars(select(VariantImage).where(
            VariantImage.variant_id == variant_id, VariantImage.is_deleted.is_(False)
        )).all()
        for image in existing:
            image.is_primary = False
        db.session.flush()
        chosen = next((im for im in existing if im.id == selected_id), None)
        if chosen is None:
            raise BadRequestException("Primary image not found")
        chosen.is_primary = True
        db.session.flush()

    def _sync_images(
        self, variant, image_requests, user_id,
        uploaded, old_paths, creating
    ):
        # No images submitted: keep existing images
        if image_requests is None:
            return

        existing = db.session.scalars(
            select(VariantImage).where(
                VariantImage.variant_id == variant.id,
                VariantImage.is_deleted.is_(False)
            )
        ).all()

        by_id = {image.id: image for image in existing}
        submitted_ids = set()
        submitted_rows = []
        chosen = None

        for item in image_requests:
            image_id = item.get("id")

            if image_id is not None:
                if (
                    creating
                    or image_id not in by_id
                    or image_id in submitted_ids
                ):
                    raise BadRequestException(
                        "Invalid or duplicate image ID"
                    )

                submitted_ids.add(image_id)
                row = by_id[image_id]

            else:
                row = VariantImage(
                    variant_id=variant.id,
                    image="",
                    is_primary=False,
                    created_at=DateUtil.now(),
                    create_uid=user_id
                )
                db.session.add(row)

            file = item.get("image")

            if file is not None:
                path = FileUtil.save_image(
                    file, ImageDirectory.PRODUCT
                )
                uploaded.append(path)

                if image_id is not None:
                    old_paths.append(row.image)

                row.image = path

            elif image_id is None:
                raise BadRequestException(
                    "New image file is required"
                )

            if item.get("is_primary"):
                if chosen is not None:
                    raise BadRequestException(
                        "Only one primary image is allowed"
                    )
                chosen = row

            submitted_rows.append(row)

        # Soft delete images missing from submitted IDs
        for image in existing:
            if image.id not in submitted_ids:
                image.is_deleted = True
                image.is_primary = False
                image.deleted_at = DateUtil.now()
                image.deleted_uid = user_id

        db.session.flush()

        if submitted_rows:
            if chosen is None:
                chosen = next(
                    (img for img in submitted_rows if img.is_primary),
                    None
                )

            if chosen is None:
                chosen = submitted_rows[0]

            db.session.flush()
            self._set_image_primary(variant.id, chosen.id)

    def _sync_stocks(self, product, variant, requests, user_id, creating):
        existing = db.session.scalars(select(VariantStock).where(
            VariantStock.variant_id == variant.id, VariantStock.is_deleted.is_(False)
        )).all()
        by_id = {s.id: s for s in existing}
        used_sizes = {s.size_id for s in existing}
        seen_ids = set()
        for item in requests:
            stock_id = item.get("id")
            size = db.session.get(Size, item["size_id"])
            if stock_id is not None:
                if creating or stock_id not in by_id or stock_id in seen_ids:
                    raise BadRequestException("Stock does not belong to this variant")
                seen_ids.add(stock_id)
                stock = by_id[stock_id]
                if stock.size_id != item["size_id"]:
                    raise BadRequestException("Cannot change size of existing stock")
                stock.low_stock_alert = item.get("low_stock_alert", 0)
                stock.updated_at = DateUtil.now()
                stock.update_uid = user_id
                if item.get("qty") is not None:
                    self._stock_change(stock, item["qty"], "MANUAL_ADJUSTMENT", None,
                                       "Stock adjustment from Product Update", user_id)
            else:
                if item["size_id"] in used_sizes:
                    raise BadRequestException("Size already exists in variant")
                used_sizes.add(item["size_id"])
                sku = f"{variant.sku_prefix}-{size.value}" if size.value else None
                if not sku or len(sku) > 100:
                    raise BadRequestException("Invalid or oversized stock SKU")
                stock = VariantStock(variant_id=variant.id, size_id=size.id, unit_id=product.unit_id,
                                     sku=sku, qty=0, low_stock_alert=item.get("low_stock_alert", 0),
                                     created_at=DateUtil.now(), create_uid=user_id)
                db.session.add(stock)
                db.session.flush()
                if item.get("qty", 0):
                    self._stock_change(stock, item["qty"], "INITIAL_STOCK", product.id,
                                       "Initial stock from product creation" if creating else "Initial stock for newly added size", user_id)
        db.session.flush()

    def _sync_variants(self, product, requests, user_id, uploaded, old_paths, creating):
        existing = db.session.scalars(select(Variant).where(
            Variant.product_id == product.id, Variant.is_deleted.is_(False)
        ).order_by(Variant.id)).all()
        by_id = {v.id: v for v in existing}
        submitted_ids = {v.get("id") for v in requests if v.get("id") is not None}
        if len(submitted_ids) != sum(v.get("id") is not None for v in requests):
            raise BadRequestException("Duplicate variant IDs")
        if creating and submitted_ids:
            raise BadRequestException("New product variants cannot have IDs")
        remaining_defaults = sum(v.is_default for v in existing if v.id not in submitted_ids)
        if remaining_defaults + sum(v.get("is_default", False) for v in requests) != 1:
            raise BadRequestException("Product must have exactly one default variant")

        # Unset existing defaults first to avoid partial unique-index violations.
        for v in existing:
            if v.id in submitted_ids:
                v.is_default = False
        db.session.flush()
        for item in requests:
            variant_id = item.get("id")
            color = db.session.get(Color, item["color_id"])
            if variant_id is not None:
                variant = by_id.get(variant_id)
                if variant is None:
                    raise BadRequestException("Variant does not belong to this product")
                if variant.color_id != color.id:
                    raise BadRequestException("Cannot change color of an existing variant")
            else:
                sku_prefix = f"{product.code}-{color.name.upper()}"
                if len(sku_prefix) > 100:
                    raise BadRequestException("Variant SKU prefix too long")
                variant = Variant(product_id=product.id, color_id=color.id, sku_prefix=sku_prefix,
                                  is_default=False, created_at=DateUtil.now(), create_uid=user_id)
                db.session.add(variant)
                db.session.flush()
            variant.cost = item.get("cost", Decimal("0"))
            variant.price = item["price"]
            variant.is_active = item.get("is_active", True)
            variant.updated_at = DateUtil.now() if variant_id is not None else None
            variant.update_uid = user_id if variant_id is not None else None
            self._sync_stocks(product, variant, item["stocks"], user_id, creating)
            self._sync_images(variant, item.get("images"), user_id, uploaded, old_paths, creating)
            variant.is_default = bool(item.get("is_default"))
            db.session.flush()

    def create(self, data, user_id):
        data = dict(data)
        self._validate_request(data)
        pair = self._pair_unit()
        uploaded, old_paths = [], []
        try:
            product = Product(category_id=data["category_id"], brand_id=data["brand_id"],
                              unit_id=pair.id, code=f"TMP-{__import__('uuid').uuid4().hex[:16]}",
                              name=data["name"], slug=self._unique_slug(data["name"]),
                              description=data.get("description"), is_active=data.get("is_active", True),
                              created_at=DateUtil.now(), create_uid=user_id)
            db.session.add(product)
            db.session.flush()
            product.code = f"PRD{product.id:05d}"
            db.session.add(ProductUnit(product_id=product.id, unit_id=pair.id,
                                       multiplier=Decimal("1"), created_at=DateUtil.now(), create_uid=user_id))
            db.session.flush()
            self._sync_variants(product, data["variants"], user_id, uploaded, old_paths, creating=True)
            result = self._map_product(product)
            db.session.commit()
            return result
        except Exception as exc:
            db.session.rollback()
            self._clean_files(uploaded, old_paths)
            if isinstance(exc, IntegrityError):
                raise DuplicateException("Product code, variant color, or stock size already exists") from exc
            raise

    def update(self, product_id, data, user_id):
        data = dict(data)
        self._validate_request(data)
        uploaded, old_paths = [], []
        try:
            product = db.session.scalar(select(Product).where(
                Product.id == product_id, Product.is_deleted.is_(False)
            ).with_for_update())
            if product is None:
                raise ResourceNotFoundException("Product not found")
            product.category_id = data["category_id"]
            product.brand_id = data["brand_id"]
            product.name = data["name"]
            product.description = data.get("description")
            product.is_active = data.get("is_active", True)
            product.updated_at = DateUtil.now()
            product.update_uid = user_id
            self._sync_variants(product, data["variants"], user_id, uploaded, old_paths, creating=False)
            result = self._map_product(product)
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            self._clean_files(uploaded, old_paths)
            if isinstance(exc, IntegrityError):
                raise DuplicateException("Duplicate product variant or stock configuration") from exc
            raise
        self._remove_old_files(old_paths)
        return result

    def delete(self, product_id, user_id, reason=None):
        try:
            deleted = self.repository.soft_delete_by_id(product_id, deleted_uid=user_id)
            if not deleted:
                raise ResourceNotFoundException("Product not found")
            if reason:
                product = db.session.get(Product, product_id)
                product.deleted_reason = reason[:500]
            db.session.commit()
        except Exception:
            db.session.rollback()
            raise
