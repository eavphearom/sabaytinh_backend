from app.repositories.product_repository import ProductRepository
from app.repositories.banner_repository import BannerRepository
from app.schemas.product_schema import ProductResponseSchema
from app.schemas.banner_schema import BannerResponseSchema
from app.schemas.web_home_schema import HomeProductResponseSchema
from app.schemas.web_home_schema import PublicProductDetailResponseSchema
from app.enums.stock_status import StockStatus
from app.exceptions.api_exception import BadRequestException, ResourceNotFoundException


class WebHomeService:
    def product_detail(self, product_id):
        if not isinstance(product_id, str) or not product_id.isascii() or not product_id.isdecimal():
            raise BadRequestException("Product ID must be a positive integer")
        normalized = product_id.lstrip("0") or "0"
        if len(normalized) > 19 or not 1 <= int(normalized) <= 9223372036854775807:
            raise BadRequestException("Product ID is outside the supported range")
        result = ProductRepository().find_public_detail(int(normalized))
        if result is None:
            raise ResourceNotFoundException("Product not found")
        product, variants, images, stocks = result
        images_by_variant = {v.id: [] for v in variants}
        stocks_by_variant = {v.id: [] for v in variants}
        for image in images:
            images_by_variant[image.variant_id].append(image)
        for stock in stocks:
            stocks_by_variant[stock.variant_id].append(stock)
        variant_data = []
        for variant in variants:
            rows = stocks_by_variant[variant.id]
            total = sum(row.qty for row in rows)
            variant_data.append({
                "id": variant.id, "product_id": product.id, "color_id": variant.color_id,
                "color_name": variant.color.name, "color_hex": variant.color.hex_code,
                "sku_prefix": variant.sku_prefix, "price": variant.price,
                "is_default": variant.is_default, "is_active": variant.is_active,
                "total_stock": total,
                "stock_status": StockStatus.from_quantity(total, 0).value,
                "images": images_by_variant[variant.id],
                "stock": [{"id": row.id, "variant_stock_id": row.id, "variant_id": row.variant_id,
                    "size_id": row.size_id, "size": row.size.value, "size_name": row.size.name,
                    "unit_id": row.unit_id, "sku": row.sku, "qty": row.qty,
                    "stock_status": StockStatus.from_quantity(row.qty, row.low_stock_alert).value}
                    for row in rows],
            })
        def public_name(entity):
            return entity.name if entity and entity.is_active and not entity.is_deleted else None
        data = {name: getattr(product, name) for name in ProductResponseSchema().fields}
        data.update(brand_name=public_name(product.brand), category_name=public_name(product.category),
                    variants=variant_data, price=min((v.price for v in variants), default=None))
        # Use the same default-variant preference as the home listing.
        data["image"] = next((images_by_variant[v.id][0].image for v in variants if images_by_variant[v.id]), None)
        return PublicProductDetailResponseSchema().dump(data)

    def products(self, filters, params):
        result = ProductRepository().find_home_products(filters, params)
        base = ProductResponseSchema()
        result["items"] = HomeProductResponseSchema(many=True).dump([
            {**{name: getattr(product, name) for name in base.fields}, "price": price, "image": image}
            for product, price, image in result["items"]
        ])
        return result

    def banners(self):
        return BannerResponseSchema(many=True).dump(BannerRepository().find_active_for_home())
