
from sqlalchemy import select, or_, func

from app.extensions import db
from app.models.product import Product
from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil


class ProductRepository(BaseRepository):

    def __init__(self):
        super().__init__(Product)

    def find_public_detail(self, product_id):
        from sqlalchemy.orm import joinedload, contains_eager
        from app.models.variant import Variant
        from app.models.variant_image import VariantImage
        from app.models.variant_stock import VariantStock
        from app.models.color import Color
        from app.models.size import Size

        product = db.session.scalar(select(Product).where(
            Product.id == product_id, Product.is_active.is_(True), Product.is_deleted.is_(False)
        ).options(joinedload(Product.category), joinedload(Product.brand)))
        if product is None:
            return None
        variants = db.session.scalars(select(Variant).join(Variant.color).where(
            Variant.product_id == product_id, Variant.is_active.is_(True), Variant.is_deleted.is_(False),
            Color.is_active.is_(True), Color.is_deleted.is_(False)
        ).options(contains_eager(Variant.color)).order_by(Variant.is_default.desc(), Variant.id)).all()
        ids = [variant.id for variant in variants]
        if not ids:
            return product, [], [], []
        images = db.session.scalars(select(VariantImage).where(
            VariantImage.variant_id.in_(ids), VariantImage.is_deleted.is_(False)
        ).order_by(VariantImage.variant_id, VariantImage.is_primary.desc(), VariantImage.id)).all()
        stocks = db.session.scalars(select(VariantStock).join(VariantStock.size).where(
            VariantStock.variant_id.in_(ids), VariantStock.is_deleted.is_(False),
            Size.is_active.is_(True), Size.is_deleted.is_(False)
        ).options(contains_eager(VariantStock.size)).order_by(VariantStock.variant_id, Size.value, VariantStock.id)).all()
        return product, variants, images, stocks

    def find_home_products(self, filters, params):
        from app.models.variant import Variant
        from app.models.variant_image import VariantImage

        prices = (select(Variant.product_id, func.min(Variant.price).label("price"))
                  .where(Variant.is_active.is_(True), Variant.is_deleted.is_(False))
                  .group_by(Variant.product_id).subquery())
        image = (select(VariantImage.image).join(Variant, Variant.id == VariantImage.variant_id)
                 .where(Variant.product_id == Product.id, Variant.is_active.is_(True),
                        Variant.is_deleted.is_(False), VariantImage.is_deleted.is_(False))
                 .order_by(Variant.is_default.desc(), Variant.id, VariantImage.is_primary.desc(), VariantImage.id)
                 .limit(1).correlate(Product).scalar_subquery())
        query = (select(Product.id, prices.c.price)
                 .outerjoin(prices, prices.c.product_id == Product.id)
                 .where(Product.is_active.is_(True), Product.is_deleted.is_(False)))
        if filters.search:
            keyword = filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(or_(*(column.ilike(f"%{keyword}%", escape="\\")
                                     for column in (Product.name, Product.code, Product.slug))))
        for name in ("category_id", "brand_id"):
            if name in params:
                query = query.where(getattr(Product, name) == params[name])
        if "min_price" in params:
            query = query.where(prices.c.price >= params["min_price"])
        if "max_price" in params:
            query = query.where(prices.c.price <= params["max_price"])
        newest = [Product.created_at.desc(), Product.id.desc()]
        if params.get("type") == "new":
            query = query.order_by(*newest).limit(15)
        # Cap the matching dataset before counting and paginating type=new.
        candidates = query.subquery()
        total = db.session.scalar(select(func.count()).select_from(candidates)) or 0
        page = (select(Product, candidates.c.price, image.label("image"))
                .join(candidates, candidates.c.id == Product.id))
        if params.get("price_sort"):
            price_order = candidates.c.price.asc() if params["price_sort"] == "asc" else candidates.c.price.desc()
            page = page.order_by(price_order.nulls_last(), *newest)
        else:
            page = page.order_by(*newest)
        rows = db.session.execute(page.offset((filters.page_no - 1) * filters.per_page)
                                  .limit(filters.per_page)).all()
        return {"items": rows, "total": total, "per_page": filters.per_page,
                "page_no": filters.page_no, "total_page": (total + filters.per_page - 1) // filters.per_page}

    # Find product by unique code
    def find_by_code(self, code):
        return db.session.scalar(
            select(Product).where(Product.code == code)
        )

    # Find product by unique slug
    def find_by_slug(self, slug):
        return db.session.scalar(
            select(Product).where(Product.slug == slug)
        )

    # Check whether a category exists on any active product
    def exists_by_category_id(self, category_id):
        query = (
            select(Product.id)
            .where(
                Product.category_id == category_id,
                Product.is_deleted.is_(False)
            )
            .limit(1)
        )
        return db.session.scalar(query) is not None

    # Get products with pagination, search, and filters
    def find_paginated(self, filters, params=None):
        params = params or {}

        query = self._query(filters.include_deleted)

        # Search by name, code, or slug
        if filters.search:
            keyword = (
                filters.search
                .replace("\\", "\\\\")
                .replace("%", "\\%")
                .replace("_", "\\_")
            )
            pattern = f"%{keyword}%"

            query = query.where(
                or_(
                    Product.name.ilike(pattern, escape="\\"),
                    Product.code.ilike(pattern, escape="\\"),
                    Product.slug.ilike(pattern, escape="\\")
                )
            )

        # Filter by Category
        category_id = self._parse_id(params.get("category_id"))

        if category_id is not None:
            query = query.where(Product.category_id == category_id)

        # Filter by Brand
        brand_id = self._parse_id(params.get("brand_id"))

        if brand_id is not None:
            query = query.where(Product.brand_id == brand_id)

        # Filter by Unit
        unit_id = self._parse_id(params.get("unit_id"))

        if unit_id is not None:
            query = query.where(Product.unit_id == unit_id)

        # Filter by active status
        is_active = self._parse_bool(params.get("is_active"))

        if is_active is not None:
            query = query.where(Product.is_active.is_(is_active))

        return PaginationUtil.paginate(
            query=query,
            model=Product,
            filters=filters,
            allowed_sort_fields={
                "id",
                "code",
                "name",
                "slug",
                "created_at",
                "is_active"
            }
        )

    def admin_list_projection(self, products):
        from app.models.variant import Variant
        from app.models.variant_stock import VariantStock
        from app.models.variant_image import VariantImage
        from app.models.category import Category
        from app.models.brand import Brand
        ids = [p.id for p in products]
        if not ids:
            return []
        variants = select(Variant.product_id,
            func.count(Variant.id).label("total_variants"),
            func.min(Variant.price).label("min_price"),
            func.max(Variant.price).label("max_price")
        ).where(Variant.product_id.in_(ids), Variant.is_deleted.is_(False)).group_by(Variant.product_id).subquery()
        stocks = select(Variant.product_id, func.sum(VariantStock.qty).label("total_stock")
        ).join(VariantStock, VariantStock.variant_id == Variant.id).where(
            Variant.product_id.in_(ids), Variant.is_deleted.is_(False), VariantStock.is_deleted.is_(False)
        ).group_by(Variant.product_id).subquery()
        image = select(VariantImage.image).join(Variant, Variant.id == VariantImage.variant_id).where(
            Variant.product_id == Product.id, Variant.is_deleted.is_(False),
            VariantImage.is_deleted.is_(False), VariantImage.image.is_not(None), VariantImage.image != ""
        ).order_by(Variant.is_default.desc(), Variant.id,
            VariantImage.is_primary.desc(), VariantImage.id).limit(1).correlate(Product).scalar_subquery()
        rows = db.session.execute(select(Product.id, Product.code, Product.name, Product.created_at,
            Product.category_id, Category.name.label("category_name"), Product.brand_id,
            Brand.name.label("brand_name"), Product.is_active, image.label("image"),
            func.coalesce(variants.c.total_variants, 0).label("total_variants"),
            variants.c.min_price, variants.c.max_price,
            func.coalesce(stocks.c.total_stock, 0).label("total_stock")
        ).outerjoin(Category, Product.category_id == Category.id)
         .outerjoin(Brand, Product.brand_id == Brand.id)
         .outerjoin(variants, variants.c.product_id == Product.id)
         .outerjoin(stocks, stocks.c.product_id == Product.id).where(Product.id.in_(ids))).mappings().all()
        by_id = {row["id"]: row for row in rows}
        return [by_id[id] for id in ids]

    def find_admin_stocks(self, product_id):
        from sqlalchemy.orm import joinedload
        from app.models.variant import Variant
        from app.models.variant_stock import VariantStock
        from app.models.variant_image import VariantImage
        product = db.session.scalar(self._query().where(Product.id == product_id).options(
            joinedload(Product.category), joinedload(Product.brand)))
        if product is None:
            return None
        variants = db.session.scalars(select(Variant).where(
            Variant.product_id == product_id, Variant.is_deleted.is_(False)
        ).options(joinedload(Variant.color)).order_by(Variant.is_default.desc(), Variant.id)).all()
        ids = [v.id for v in variants]
        if not ids:
            return product, [], [], []
        stocks = db.session.scalars(select(VariantStock).where(
            VariantStock.variant_id.in_(ids), VariantStock.is_deleted.is_(False)
        ).options(joinedload(VariantStock.size)).order_by(VariantStock.variant_id, VariantStock.id)).all()
        images = db.session.scalars(select(VariantImage).where(
            VariantImage.variant_id.in_(ids), VariantImage.is_deleted.is_(False),
            VariantImage.image.is_not(None), VariantImage.image != ""
        ).order_by(VariantImage.variant_id, VariantImage.is_primary.desc(), VariantImage.id)).all()
        return product, variants, stocks, images

    @staticmethod
    def _parse_id(value):
        if value is None or value == "":
            return None

        try:
            parsed = int(value)
        except (TypeError, ValueError):
            from app.exceptions.api_exception import BadRequestException
            raise BadRequestException("Invalid filter ID")

        if parsed <= 0:
            from app.exceptions.api_exception import BadRequestException
            raise BadRequestException("Filter ID must be positive")

        return parsed

    @staticmethod
    def _parse_bool(value):
        if value is None or value == "":
            return None

        if isinstance(value, bool):
            return value

        if str(value).lower() in ("true", "1"):
            return True

        if str(value).lower() in ("false", "0"):
            return False

        from app.exceptions.api_exception import BadRequestException
        raise BadRequestException("Invalid is_active value")
