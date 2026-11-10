import os
import unittest
from datetime import datetime
from decimal import Decimal
from sqlalchemy import event
from app.extensions import db
from app.models import Product, Variant, VariantStock, VariantImage, Color, Size
from app.routes.v1.admin.product_routes import product_bp
from tests import test_admin_customers as customer_fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class AdminProductReadTests(unittest.TestCase):
    tearDownClass = classmethod(customer_fixture.AdminCustomerTests.tearDownClass.__func__)
    tearDown = customer_fixture.AdminCustomerTests.tearDown
    setUp = customer_fixture.AdminCustomerTests.setUp
    add_order = customer_fixture.AdminCustomerTests.add_order

    @classmethod
    def setUpClass(cls):
        customer_fixture.AdminCustomerTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(product_bp)

    def get(self, suffix="", user=4):
        return self.client.get("/api/v1/admin/products" + suffix, headers=self.headers.get(user, {}))

    def variants(self):
        db.session.add_all([Color(id=2, name="Blue"), Color(id=3, name="Hidden")])
        db.session.flush()
        db.session.add_all([
            Variant(id=2, product_id=1, color_id=2, sku_prefix="BLUE", price=35, is_active=False),
            Variant(id=3, product_id=1, color_id=3, sku_prefix="HIDDEN", price=999, is_deleted=True),
        ])
        db.session.flush()
        db.session.add_all([
            VariantStock(id=3, variant_id=2, size_id=1, unit_id=1, sku="BLUE-42", qty=2, low_stock_alert=3),
            VariantStock(id=4, variant_id=2, size_id=2, unit_id=1, sku="BLUE-43", qty=99, is_deleted=True),
            VariantStock(id=5, variant_id=3, size_id=1, unit_id=1, sku="HIDDEN-42", qty=999),
        ])
        db.session.commit()

    def test_stock_normal_and_multi_variant(self):
        self.variants()
        db.session.get(VariantStock, 2).qty = 0
        db.session.commit()
        response = self.get("/1/stocks")
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json["data"]
        self.assertEqual(data["total_stock"], 7)
        self.assertEqual(data["total_variants"], 2)
        self.assertEqual(data["total_sizes"], 3)
        self.assertEqual(data["low_stock_sizes"], 1)
        self.assertEqual(data["out_of_stock_sizes"], 1)
        self.assertEqual(data["available_sizes"], 2)
        self.assertEqual(data["variants"][0]["stocks"][0]["size"], "42")
        self.assertEqual(data["variants"][0]["color_name"], "Black")
        self.assertIsNone(data["variants"][0]["color_hex"])
        self.assertEqual(data["image"], "http://localhost/uploads/products/a.png")

    def test_missing_stocks_nullable_sizes_and_missing_product(self):
        db.session.get(VariantStock, 1).is_deleted = True
        db.session.get(VariantStock, 2).is_deleted = True
        db.session.get(VariantImage, 1).is_deleted = True
        db.session.commit()
        data = self.get("/1/stocks").json["data"]
        self.assertEqual(data["total_stock"], 0)
        self.assertEqual(data["variants"][0]["stocks"], [])
        self.assertIsNone(data["image"])
        for id in (0, 999, 99999999999999999999999):
            self.assertEqual(self.get(f"/{id}/stocks").status_code, 404)
        db.session.get(VariantStock, 1).is_deleted = False
        size = db.session.get(Size, 1); size.name = size.value = None
        db.session.commit()
        self.assertIsNone(self.get("/1/stocks").json["data"]["variants"][0]["stocks"][0]["size"])
        db.session.get(Product, 1).is_deleted = True
        db.session.commit()
        self.assertEqual(self.get("/1/stocks").status_code, 404)

    def test_list_exact_contract_and_aggregates(self):
        self.variants()
        db.session.get(Product, 1).created_at = datetime(2026, 11, 10, 10, 30)
        db.session.commit()
        result = self.get().json
        self.assertEqual(result["pagination"]["total"], 1)
        row = result["data"][0]
        self.assertEqual(set(row), {"id", "code", "name", "image", "created_at", "category_id", "category_name",
            "brand_id", "brand_name", "total_variants", "min_price", "max_price", "total_stock", "is_active"})
        self.assertEqual(row["total_variants"], 2)
        self.assertEqual(row["total_stock"], 12)
        self.assertEqual(row["min_price"], 10.125)
        self.assertEqual(row["max_price"], 35)
        self.assertEqual(row["created_at"], "2026-11-10T10:30:00")
        self.assertEqual(row["category_name"], "Shoes")

    def test_no_variants_and_empty_page(self):
        db.session.get(Variant, 1).is_deleted = True
        db.session.commit()
        row = self.get().json["data"][0]
        for key in ("total_stock", "total_variants"):
            self.assertEqual(row[key], 0)
        for key in ("min_price", "max_price", "image"):
            self.assertIsNone(row[key])
        self.assertEqual(self.get("/1/stocks").json["data"]["variants"], [])
        self.assertEqual(self.get("?page_no=2").json["data"], [])

    def test_image_priority_and_deterministic_fallback(self):
        self.variants()
        db.session.add_all([
            VariantImage(id=2, variant_id=1, image="/uploads/secondary.png", is_primary=False),
            VariantImage(id=3, variant_id=2, image="https://example.com/blue.png", is_primary=True),
        ])
        db.session.commit()
        self.assertTrue(self.get().json["data"][0]["image"].endswith("a.png"))
        db.session.get(VariantImage, 1).is_deleted = True
        db.session.commit()
        self.assertTrue(self.get().json["data"][0]["image"].endswith("secondary.png"))
        db.session.get(VariantImage, 2).is_deleted = True
        db.session.commit()
        for suffix in ("", "/1/stocks"):
            data = self.get(suffix).json["data"]
            self.assertEqual((data[0] if isinstance(data, list) else data)["image"], "https://example.com/blue.png")

    def test_visibility_filters_sorting_and_legacy_detail(self):
        db.session.add(Product(id=2, name="Another", code="PRD00002", slug="another", category_id=1, brand_id=1, unit_id=1, is_active=False))
        db.session.commit()
        self.assertEqual([r["id"] for r in self.get("?sort_by=name&sort_dir=asc").json["data"]], [2, 1])
        self.assertEqual(self.get("?search=Shoe&category_id=1&brand_id=1&unit_id=1").json["pagination"]["total"], 1)
        self.assertEqual(self.get("?is_active=false").json["data"][0]["id"], 2)
        db.session.get(Product, 2).is_deleted = True; db.session.commit()
        self.assertEqual(self.get().json["pagination"]["total"], 1)
        self.assertEqual(self.get("?include_deleted=true").json["pagination"]["total"], 2)
        for suffix in ("?sort_by=invalid", "?page_no=0", "?per_page=101"):
            self.assertEqual(self.get(suffix).status_code, 400)
        detail = self.get("/1").json["data"]
        self.assertIn("variants", detail)
        self.assertIn("description", detail)
        self.assertEqual(self.get("/pagination").json, self.get().json)

    def test_auth_and_bounded_queries(self):
        self.variants()
        for suffix in ("", "/1/stocks"):
            self.assertEqual(self.get(suffix, user=0).status_code, 401)
            self.assertEqual(self.get(suffix, user=1).status_code, 403)
            statements = []
            def record(*args): statements.append(args[2])
            event.listen(db.engine, "before_cursor_execute", record)
            try:
                self.assertEqual(self.get(suffix).status_code, 200)
            finally:
                event.remove(db.engine, "before_cursor_execute", record)
            self.assertLessEqual(len(statements), 7)
