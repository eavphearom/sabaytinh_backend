from datetime import datetime, timedelta
from decimal import Decimal
import os
import unittest

from sqlalchemy import event, select

from app.extensions import db
from app.exceptions.handlers import register_error_handlers
from app.models import Product, Variant, VariantImage, VariantStock, Size, Banner, Category, Brand, Color
from app.routes.v1.web.catalog_routes import web_home_bp
from tests import test_checkout_service as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class WebHomePostgresTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = fixture.CheckoutServicePostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.CheckoutServicePostgresTests.setUpClass.__func__(cls)
        register_error_handlers(cls.app)
        cls.app.register_blueprint(web_home_bp)

    def setUp(self):
        fixture.CheckoutServicePostgresTests.setUp(self)
        db.session.get(Product, 1).created_at = datetime(2025, 1, 1)
        db.session.add_all([Category(id=2, name="Other", slug="other"),
                            Brand(id=2, name="Other", slug="other"), Color(id=2, name="White")])
        db.session.flush()
        for id in range(2, 21):
            db.session.add(Product(id=id, category_id=2 if id % 2 == 0 else 1,
                brand_id=2 if id % 3 == 0 else 1, unit_id=1, code=f"HOME{id}",
                name=f"Home shoe {id}", slug=f"home-{id}",
                created_at=datetime(2025, 1, 1) + timedelta(days=id)))
        db.session.flush()
        for id in range(2, 21):
            db.session.add(Variant(id=id, product_id=id, color_id=1, sku_prefix=f"HOME{id}",
                                   price=Decimal(id), is_default=True))
        db.session.add_all([
            Banner(id=3, title="Third", image="/uploads/banners/3.png"),
            Banner(id=1, title="First", image="/uploads/banners/1.png"),
            Banner(id=2, title="Inactive", image="/uploads/banners/2.png", is_active=False),
            Banner(id=4, title="Deleted", image="/uploads/banners/4.png", is_deleted=True),
        ])
        db.session.commit()
        self.client = self.app.test_client()

    def products(self, query=""):
        return self.client.get("/api/v1/web/home/products" + query)

    def test_public_pagination_response_and_safe_fields(self):
        response = self.products("?page_no=2&per_page=3")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["pagination"], {"page_no": 2, "per_page": 3, "total": 20, "total_page": 7})
        self.assertEqual([p["id"] for p in response.json["data"]], [17, 16, 15])
        self.assertEqual(response.json["data"][0]["price"], "17.00000")
        self.assertNotIn("cost", response.json["data"][0])
        self.assertEqual(response.json["data"][0]["created_at"], "2025-01-18 00:00:00")

    def test_new_is_capped_at_fifteen_before_pagination(self):
        response = self.products("?type=new")
        self.assertEqual(len(response.json["data"]), 15)
        self.assertEqual(response.json["pagination"]["total"], 15)
        self.assertEqual([p["id"] for p in response.json["data"]], list(range(20, 5, -1)))
        response = self.products("?type=new&page_no=3&per_page=6")
        self.assertEqual([p["id"] for p in response.json["data"]], [8, 7, 6])
        self.assertEqual(response.json["pagination"]["total_page"], 3)

    def test_combined_search_category_brand_and_price_filters(self):
        response = self.products("?search=HOME&category_id=2&brand_id=2&min_price=5&max_price=15&price_sort=asc")
        self.assertEqual([p["id"] for p in response.json["data"]], [6, 12])
        response = self.products("?type=new&category_id=2&min_price=17")
        self.assertEqual([p["id"] for p in response.json["data"]], [20, 18])

    def test_price_uses_minimum_active_variant_without_duplicate_products(self):
        db.session.add(Variant(id=30, product_id=20, color_id=2, sku_prefix="CHEAP", price=Decimal("0.50")))
        db.session.commit()
        response = self.products("?price_sort=asc&per_page=1")
        self.assertEqual(response.json["data"][0]["id"], 20)
        self.assertEqual(response.json["data"][0]["price"], "0.50000")
        self.assertEqual(response.json["pagination"]["total"], 20)
        self.assertEqual(self.products("?min_price=19&max_price=20").json["pagination"]["total"], 1)
        for attribute in ("is_active", "is_deleted"):
            variant = db.session.get(Variant, 30)
            variant.is_active = True
            variant.is_deleted = False
            setattr(variant, attribute, attribute == "is_deleted")
            db.session.commit()
            self.assertEqual(self.products("?price_sort=desc&per_page=1").json["data"][0]["price"], "20.00000")

    def test_inactive_and_deleted_products_never_leak(self):
        db.session.get(Product, 20).is_active = False
        db.session.get(Product, 19).is_deleted = True
        db.session.commit()
        response = self.products("?type=new&per_page=100")
        self.assertNotIn(20, [p["id"] for p in response.json["data"]])
        self.assertNotIn(19, [p["id"] for p in response.json["data"]])
        self.assertEqual(self.products("?include_deleted=true").status_code, 400)

    def test_search_wildcards_are_literal(self):
        db.session.get(Product, 2).name = "100% shoe_test"
        db.session.commit()
        response = self.products("?search=%25")
        self.assertEqual([p["id"] for p in response.json["data"]], [2])

    def test_new_tie_breaker_is_descending_id(self):
        db.session.get(Product, 19).created_at = db.session.get(Product, 20).created_at
        db.session.commit()
        self.assertEqual([p["id"] for p in self.products("?type=new&per_page=2").json["data"]], [20, 19])

    def test_empty_results_and_beyond_last_page(self):
        response = self.products("?search=does-not-exist")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], [])
        self.assertEqual(response.json["pagination"]["total_page"], 0)
        self.assertEqual(self.products("?page_no=99").json["data"], [])

    def test_validation_errors(self):
        for query in ("page_no=0", "page_no=999999999999999999999", "per_page=101", "page_no=no", "category_id=-1", "brand_id=abc",
                      "price_sort=up", "min_price=NaN", "max_price=Infinity", "min_price=-1",
                      "min_price=20&max_price=10", "type=popular", "type=new&price_sort=asc"):
            with self.subTest(query=query):
                self.assertEqual(self.products("?" + query).status_code, 400)

    def test_banners_active_only_in_id_order_with_image_urls(self):
        response = self.client.get("/api/v1/web/home/banners")
        self.assertEqual(response.status_code, 200)
        self.assertEqual([b["id"] for b in response.json["data"]], [1, 3])
        self.assertEqual(response.json["data"][0]["image"], "http://localhost/uploads/banners/1.png")
        for banner in db.session.scalars(select(Banner)):
            banner.is_active = False
        db.session.commit()
        self.assertEqual(self.client.get("/api/v1/web/home/banners").json["data"], [])

    def test_query_count_is_constant_and_product_images_use_file_util(self):
        counts = []
        def count(*args):
            counts.append(1)
        event.listen(db.engine, "before_cursor_execute", count)
        try:
            response = self.products("?per_page=100")
        finally:
            event.remove(db.engine, "before_cursor_execute", count)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(counts), 2)
        product = next(p for p in response.json["data"] if p["id"] == 1)
        self.assertEqual(product["image"], "http://localhost/uploads/products/a.png")

    def test_active_product_without_active_variants_has_no_public_price(self):
        db.session.get(Variant, 20).is_active = False
        db.session.commit()
        response = self.products("?search=HOME20")
        self.assertEqual(response.json["data"][0]["price"], None)
        self.assertEqual(self.products("?search=HOME20&min_price=0").json["data"], [])

    def test_public_detail_matches_react_fields_and_excludes_costs(self):
        response = self.products("/1")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["error"])
        self.assertNotIn("pagination", response.json)
        data = response.json["data"]
        self.assertEqual((data["id"], data["brand_name"], data["category_name"]), (1, "Brand", "Shoes"))
        self.assertEqual(data["price"], "10.12500")
        variant = data["variants"][0]
        self.assertEqual(variant["color_name"], "Black")
        self.assertEqual(variant["total_stock"], 10)
        self.assertEqual(variant["stock_status"], "IN_STOCK")
        self.assertEqual(variant["images"][0]["image"], "http://localhost/uploads/products/a.png")
        self.assertEqual(variant["stock"][0]["size"], "42")
        self.assertEqual(variant["stock"][0]["variant_stock_id"], 1)
        self.assertNotIn("cost", variant)
        self.assertNotIn("low_stock_alert", variant["stock"][0])

    def test_detail_nonexistent_inactive_and_deleted_products_are_404(self):
        self.assertEqual(self.products("/99999").status_code, 404)
        db.session.get(Product, 1).is_active = False
        db.session.commit()
        self.assertEqual(self.products("/1").status_code, 404)
        db.session.get(Product, 1).is_active = True
        db.session.get(Product, 1).is_deleted = True
        db.session.commit()
        self.assertEqual(self.products("/1").status_code, 404)

    def test_detail_invalid_ids_are_400(self):
        for id in ("0", "-1", "abc", "1.5", "+1", "9223372036854775808", "9" * 100):
            with self.subTest(id=id):
                self.assertEqual(self.products("/" + id).status_code, 400)

    def test_detail_filters_unavailable_variants_colors_images_and_sizes(self):
        db.session.add(Variant(id=30, product_id=1, color_id=2, sku_prefix="WHITE", price=Decimal("3")))
        db.session.add(VariantImage(id=30, variant_id=1, image="/uploads/deleted.png", is_deleted=True))
        db.session.get(Size, 2).is_active = False
        db.session.commit()
        data = self.products("/1").json["data"]
        self.assertEqual([v["id"] for v in data["variants"]], [1, 30])
        self.assertEqual(data["variants"][0]["total_stock"], 5)
        self.assertEqual(len(data["variants"][0]["images"]), 1)
        for attribute in ("is_active", "is_deleted"):
            variant = db.session.get(Variant, 30)
            variant.is_active = True
            variant.is_deleted = False
            setattr(variant, attribute, attribute == "is_deleted")
            db.session.commit()
            self.assertEqual([v["id"] for v in self.products("/1").json["data"]["variants"]], [1])
        variant = db.session.get(Variant, 30)
        variant.is_deleted = False
        db.session.get(Color, 2).is_active = False
        db.session.get(VariantStock, 1).is_deleted = True
        db.session.commit()
        data = self.products("/1").json["data"]
        self.assertEqual([v["id"] for v in data["variants"]], [1])
        self.assertEqual(data["variants"][0]["stock"], [])

    def test_detail_out_of_stock_and_empty_variants_remain_displayable(self):
        db.session.get(VariantStock, 1).qty = 0
        db.session.get(VariantStock, 2).qty = 0
        db.session.commit()
        response = self.products("/1")
        self.assertEqual(response.status_code, 200)
        variant = response.json["data"]["variants"][0]
        self.assertEqual(variant["total_stock"], 0)
        self.assertEqual(variant["stock_status"], "OUT_OF_STOCK")
        self.assertTrue(all(s["stock_status"] == "OUT_OF_STOCK" for s in variant["stock"]))
        db.session.get(Variant, 1).is_active = False
        db.session.commit()
        data = self.products("/1").json["data"]
        self.assertEqual(data["variants"], [])
        self.assertIsNone(data["price"])
        self.assertIsNone(data["image"])

    def test_detail_batched_queries_do_not_grow_with_variants(self):
        for extra in (False, True):
            if extra:
                db.session.add(Variant(id=30, product_id=1, color_id=2, sku_prefix="WHITE", price=Decimal("3")))
                db.session.flush()
                db.session.add(VariantImage(id=30, variant_id=30, image="/uploads/products/white.png"))
                db.session.add(VariantStock(id=30, variant_id=30, size_id=1, unit_id=1, sku="WHITE-42", qty=2))
                db.session.commit()
            db.session.remove()
            calls = []
            def count(*args):
                calls.append(1)
            event.listen(db.engine, "before_cursor_execute", count)
            try:
                response = self.products("/1")
            finally:
                event.remove(db.engine, "before_cursor_execute", count)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(len(calls), 4)
            if extra:
                self.assertEqual(len(response.json["data"]["variants"]), 2)
                self.assertEqual(response.json["data"]["variants"][1]["stock"][0]["variant_stock_id"], 30)


class WebHomeRegistrationTests(unittest.TestCase):
    def test_factory_registers_both_endpoints_once(self):
        from app import create_app
        app = create_app()
        for path in ("/api/v1/web/home/products", "/api/v1/web/home/banners", "/api/v1/web/home/products/<product_id>"):
            self.assertEqual(sum(rule.rule == path and "GET" in rule.methods
                                 for rule in app.url_map.iter_rules()), 1)
