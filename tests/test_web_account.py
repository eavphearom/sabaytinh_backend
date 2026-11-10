from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from flask_jwt_extended import create_access_token
from sqlalchemy import event

from app.extensions import db, jwt
from app.exceptions.handlers import register_error_handlers
from app.models import User, RefreshSession, Order, OrderItem
from app.routes.v1.web.account_routes import web_account_bp
from app.routes.v1.web.order_routes import web_order_bp
from app.security.jwt_utils import register_jwt_handlers
from app.services.web_account_service import WebAccountService
from app.common.filters import BaseFilter
from tests import test_checkout_service as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class WebAccountTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = fixture.CheckoutServicePostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.CheckoutServicePostgresTests.setUpClass.__func__(cls)
        cls.app.config["JWT_SECRET_KEY"] = "account-test-key-never-use-in-real-application"
        jwt.init_app(cls.app)
        register_jwt_handlers(jwt)
        register_error_handlers(cls.app)
        cls.app.register_blueprint(web_account_bp)
        cls.app.register_blueprint(web_order_bp)

    def setUp(self):
        fixture.CheckoutServicePostgresTests.setUp(self)
        db.session.add_all([User(id=id, username=f"Other{id}", email=f"other{id}@test.invalid",
                                 password="test", role_id=1) for id in (2, 3)])
        db.session.flush()
        statuses = ["PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED", "PENDING", "DELIVERED"]
        for id, status in enumerate(statuses, 1):
            db.session.add(Order(id=id, order_code=f"ORD-{id:03d}", customer_id=2 if id == 7 else 1,
                delivery_method_id=1, delivery_method_name="Delivery", recipient_name="Recipient-only-term",
                recipient_phone="012345678", delivery_address="Phnom Penh", order_status=status,
                total_amount=Decimal(100 - id), is_deleted=id == 6,
                created_at=datetime(2026, 11, 10, 10, 30) + timedelta(minutes=id)))
        db.session.flush()
        for id, deleted, quantity in ((1, True, 9), (3, False, 2), (2, False, 5)):
            db.session.add(OrderItem(id=id, order_id=1, product_id=1, variant_id=1, variant_stock_id=1,
                product_name=f"Snapshot{id}", sku="SKU", quantity=quantity, unit_price=Decimal("40.25"),
                subtotal=Decimal("40.25") * quantity, color_name="Black", size_name="42",
                image="/uploads/products/a.png", is_deleted=deleted))
        self.headers, self.sids = {}, {}
        for id in (1, 2, 3):
            sid = uuid4()
            self.sids[id] = sid
            db.session.add(RefreshSession(id=sid, user_id=id, token_hash="test", revoked=False,
                                          expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            self.headers[id] = {"Authorization": "Bearer " + create_access_token(
                identity=str(id), additional_claims={"sid": str(sid)})}
        db.session.commit()
        self.client = self.app.test_client()

    def get(self, suffix, user=1):
        return self.client.get("/api/v1/web/account/" + suffix, headers=self.headers[user] if user else {})

    def test_overview_counts_cancelled_and_isolates_customer(self):
        response = self.get("overview")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], {"totalOrders": 5, "inProgress": 3, "completed": 1})
        self.assertEqual(self.get("overview", 2).json["data"], {"totalOrders": 1, "inProgress": 0, "completed": 1})
        self.assertEqual(self.get("overview", 3).json["data"], {"totalOrders": 0, "inProgress": 0, "completed": 0})
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_authentication_and_revocation(self):
        for endpoint in ("overview", "orders"):
            self.assertEqual(self.get(endpoint, None).status_code, 401)
            self.assertEqual(self.client.get("/api/v1/web/account/" + endpoint,
                headers={"Authorization": "Bearer invalid"}).status_code, 401)
        db.session.get(RefreshSession, self.sids[1]).revoked = True
        db.session.commit()
        for endpoint in ("overview", "orders"):
            self.assertEqual(self.get(endpoint).status_code, 401)

    def test_preview_first_nondeleted_row_and_row_count(self):
        response = self.get("orders?search=ORD-001")
        self.assertEqual(response.status_code, 200)
        row = response.json["data"][0]
        self.assertEqual(set(row), {"id", "orderCode", "createdAt", "total", "orderStatus", "paymentStatus", "totalItems", "previewItem"})
        self.assertEqual(row["totalItems"], 2)
        self.assertEqual(row["createdAt"], "2026-11-10T10:31:00")
        self.assertEqual(row["total"], 99.0)
        self.assertEqual(row["previewItem"], {"productName": "Snapshot2", "image": "http://localhost/uploads/products/a.png",
            "colorName": "Black", "sizeName": "42", "quantity": 5, "unitPrice": 40.25})
        empty = self.get("orders?search=ORD-002").json["data"][0]
        self.assertIsNone(empty["previewItem"])
        self.assertEqual(empty["totalItems"], 0)

    def test_pagination_default_newest_and_customer_isolation(self):
        response = self.get("orders?page_no=2&per_page=2")
        self.assertEqual([r["id"] for r in response.json["data"]], [3, 2])
        self.assertEqual(response.json["pagination"], {"page_no": 2, "per_page": 2, "total": 5, "total_page": 3})
        self.assertEqual([r["id"] for r in self.get("orders", 2).json["data"]], [7])
        self.assertEqual(self.get("orders?search=ORD-007").json["data"], [])
        self.assertEqual(self.get("orders?customer_id=2").status_code, 400)

    def test_all_allowed_sort_columns_and_directions(self):
        for key in ("id", "createdAt", "total"):
            for direction in ("asc", "desc"):
                response = self.get(f"orders?sort_by={key}&sort_dir={direction}")
                expected = list(range(1, 6))
                if (direction == "desc") != (key == "total"):
                    expected.reverse()
                self.assertEqual([r["id"] for r in response.json["data"]], expected)

    def test_search_is_order_code_only_literal_and_status_combines(self):
        self.assertEqual(self.get("orders?search=Recipient-only-term").json["data"], [])
        self.assertEqual(self.get("orders?search=Dara").json["data"], [])
        for id, status in enumerate(("PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"), 1):
            response = self.get(f"orders?search=ord&status={status}&per_page=1")
            self.assertEqual([r["id"] for r in response.json["data"]], [id])
            self.assertEqual(response.json["pagination"]["total"], 1)
        db.session.get(Order, 1).order_code = "ORD-100%"
        db.session.commit()
        self.assertEqual([r["id"] for r in self.get("orders?search=%25").json["data"]], [1])

    def test_invalid_filters_return_400(self):
        for query in ("page_no=0", "per_page=101", "page_no=x", "sort_by=orderCode", "sort_by=created_at",
                      "sort_dir=bad", "status=CONFIRMED", "status=", "status=paid", "payment_status=PAID",
                      "include_deleted=true", "search=a&search=b", "page_no=999999999999999999999"):
            with self.subTest(query=query):
                self.assertEqual(self.get("orders?" + query).status_code, 400)

    def test_empty_results(self):
        for suffix, user in (("orders", 3), ("orders?search=missing", 1), ("orders?page_no=99", 1)):
            response = self.get(suffix, user)
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"], [])

    def test_legacy_order_endpoints_keep_original_mapping(self):
        response = self.client.get("/api/v1/web/orders?search=ORD-001", headers=self.headers[1])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"][0]["total_items"], 7)
        self.assertIn("order_code", response.json["data"][0])
        response = self.client.get("/api/v1/web/orders/account-overview", headers=self.headers[1])
        self.assertEqual(response.json["data"], {"total_orders": 5, "in_progress": 3, "completed": 1})

    def test_batch_loading_and_overview_query_counts(self):
        db.session.remove()
        calls = []
        def count(*args):
            calls.append(1)
        event.listen(db.engine, "before_cursor_execute", count)
        try:
            with self.app.test_request_context():
                service = WebAccountService()
                service.overview(1)
                self.assertEqual(len(calls), 1)
                calls.clear()
                service.orders(1, BaseFilter(sort_by="createdAt"))
                self.assertEqual(len(calls), 3)  # Count, page, batched items.
        finally:
            event.remove(db.engine, "before_cursor_execute", count)


class WebAccountRegistrationTests(unittest.TestCase):
    def test_factory_registers_account_and_keeps_order_routes(self):
        from app import create_app
        paths = [rule.rule for rule in create_app().url_map.iter_rules()]
        for path in ("/api/v1/web/account/overview", "/api/v1/web/account/orders",
                     "/api/v1/web/orders", "/api/v1/web/orders/account-overview"):
            self.assertEqual(paths.count(path), 1)
