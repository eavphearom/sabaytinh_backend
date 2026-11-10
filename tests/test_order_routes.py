from concurrent.futures import ThreadPoolExecutor
import base64
import hashlib
import hmac
from datetime import datetime, timedelta, timezone
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask_jwt_extended import create_access_token
import sqlalchemy as sa

from app.extensions import db, jwt
from app.exceptions.handlers import register_error_handlers
from app.models import User, Role, RefreshSession, Order, Payment, Invoice, OrderStatusHistory, StockMovement, VariantStock
from app.routes.v1.web.order_routes import web_order_bp
from app.routes.v1.admin.order_routes import admin_order_bp
from app.routes.v1.payway_callback_routes import register_payway_callback
from app.security.jwt_utils import register_jwt_handlers
from app.services.checkout_service import CheckoutService
from app.services.order_service import OrderService
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_strategy import GatewayError
from tests import test_checkout_service as checkout_tests
from tests import test_payment_service as payment_tests


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class OrderAPIPostgresTests(unittest.TestCase):
    tearDownClass = classmethod(checkout_tests.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = checkout_tests.CheckoutServicePostgresTests.tearDown
    payload = checkout_tests.CheckoutServicePostgresTests.payload

    @classmethod
    def setUpClass(cls):
        checkout_tests.CheckoutServicePostgresTests.setUpClass.__func__(cls)
        cls.app.config.update(JWT_SECRET_KEY="order-api-test-key-which-is-not-a-real-secret",
                              PAYWAY_CALLBACK_URL="https://example.test/testing/aba-callback")
        jwt.init_app(cls.app)
        register_jwt_handlers(jwt)
        register_error_handlers(cls.app)
        cls.app.register_blueprint(web_order_bp)
        cls.app.register_blueprint(admin_order_bp)
        register_payway_callback(cls.app)

    def setUp(self):
        checkout_tests.CheckoutServicePostgresTests.setUp(self)
        self.app.config.update(
            PAYWAY_PUBLIC_API_ENABLED=False, PAYWAY_CALLBACK_APPROVED=False, PAYWAY_SANDBOX_VERIFIED=False, PAYWAY_WORKER_VERIFIED=False,
            PAYWAY_SANDBOX_ENABLED=True, PAYWAY_BASE_URL="https://checkout-sandbox.payway.com.kh",
            PAYWAY_MERCHANT_ID="test_merchant", PAYWAY_API_KEY="not-a-real-key",
            PAYWAY_CALLBACK_SECRET="test-callback-secret",
            PAYWAY_CONNECT_TIMEOUT=5, PAYWAY_READ_TIMEOUT=15, PAYWAY_LEASE_SECONDS=90,
        )
        db.session.add(Role(id=2, name="Administrator", code="ADMIN"))
        db.session.flush()
        db.session.add_all([
            User(id=2, username="Admin", email="a@example.test", password="hash", role_id=2),
            User(id=3, username="Other", email="o@example.test", password="hash", role_id=1),
        ])
        db.session.commit()
        self.headers = {}
        for id in (1, 2, 3):
            sid = uuid4()
            db.session.add(RefreshSession(id=sid, user_id=id, token_hash="test", revoked=False,
                                          expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            self.headers[id] = {"Authorization": "Bearer " + create_access_token(identity=str(id), additional_claims={"sid": str(sid)})}
        db.session.commit()
        self.ids = CheckoutService().checkout(1, self.payload())
        self.id = self.ids["order_id"]
        self.client = self.app.test_client()
        self.gateway = payment_tests.MockGateway()
        self.gateway.status = "PENDING"
        self.gateway.fail = False
        self.factory_patch = patch("app.services.payments.payment_service.PaymentStrategyFactory.resolve", return_value=self.gateway)
        self.factory_patch.start()
        self.addCleanup(self.factory_patch.stop)

    def enable(self):
        self.app.config.update(PAYWAY_PUBLIC_API_ENABLED=True, PAYWAY_CALLBACK_APPROVED=True,
                               PAYWAY_SANDBOX_VERIFIED=True, PAYWAY_WORKER_VERIFIED=True)

    def get(self, suffix, user=1):
        return self.client.get("/api/v1/web/orders" + suffix, headers=self.headers[user])

    def status(self, value):
        return self.client.patch(f"/api/v1/admin/orders/{self.id}/status",
            headers=self.headers[2], json={"order_status": value, "note": "Admin update"})

    def pay(self):
        PaymentService().initialize(self.ids["payment_id"])
        self.gateway.status = "APPROVED"
        PaymentService(paid_hook=lambda event: None).verify(self.ids["payment_id"])

    def test_jwt_auth_admin_authorization_and_ownership(self):
        self.assertEqual(self.client.get("/api/v1/web/orders").status_code, 401)
        self.assertEqual(self.client.get("/api/v1/web/orders", headers={"Authorization": "Bearer invalid"}).status_code, 401)
        self.assertEqual(self.client.get("/api/v1/admin/orders", headers=self.headers[1]).status_code, 403)
        for suffix in (f"/{self.id}", f"/{self.id}/payment/check"):
            response = self.get(suffix, user=3)
            self.assertEqual(response.status_code, 404)
            self.assertTrue(response.json["error"])
        response = self.client.patch(f"/api/v1/web/orders/{self.id}/cancel", headers=self.headers[3], json={"reason": "No"})
        self.assertEqual(response.status_code, 404)
        db.session.get(User, 1).status = "INACTIVE"
        db.session.commit()
        self.assertEqual(self.get("").status_code, 401)

    def test_history_overview_details_and_admin_filters(self):
        response = self.get("")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["pagination"], {"per_page": 10, "total": 1, "total_page": 1, "page_no": 1})
        row = response.json["data"][0]
        self.assertEqual(row["total"], "21.50")
        self.assertEqual(row["preview_item"]["qty"], 2)
        self.assertTrue(row["preview_item"]["image"].startswith("http://localhost/uploads/"))
        self.assertEqual(self.get("", user=3).json["data"], [])
        self.assertEqual(self.get("/account-overview").json["data"], {"total_orders": 1, "in_progress": 1, "completed": 0})
        detail = self.get(f"/{self.id}").json["data"]
        self.assertEqual(set(detail["customer"]), {"id", "username", "email", "phone"})
        self.assertNotIn("gateway_lease_token", detail["payments"][0])
        response = self.client.get("/api/v1/admin/orders?customer_id=1&order_status=PENDING&search=ORD", headers=self.headers[2])
        self.assertEqual(response.json["pagination"]["total"], 1)
        self.assertEqual(response.json["data"][0]["total_items"], 2)
        response = self.client.get("/api/v1/admin/orders?payment_status=PAID", headers=self.headers[2])
        self.assertEqual(response.json["pagination"]["total"], 0)
        self.assertEqual(self.get("?include_deleted=true").status_code, 400)

    def test_disabled_checkout_and_callback_do_not_write(self):
        for key in ("PAYWAY_PUBLIC_API_ENABLED", "PAYWAY_CALLBACK_APPROVED", "PAYWAY_SANDBOX_VERIFIED", "PAYWAY_SANDBOX_ENABLED"):
            self.enable()
            self.app.config["PAYWAY_SANDBOX_ENABLED"] = True
            self.app.config[key] = False
            response = self.client.post("/api/v1/web/checkout", headers=self.headers[1], json=self.payload())
            self.assertEqual(response.status_code, 503)
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(Order)), 1)
            self.assertEqual(db.session.get(VariantStock, 1, populate_existing=True).qty, 3)
        response = self.client.post("/testing/aba-callback", json={"tran_id": "bad", "status": "0"})
        self.assertEqual(response.status_code, 503)

    def test_checkout_flow_after_commit_and_gateway_failure_returns_existing_order(self):
        self.enable()
        response = self.client.post("/api/v1/web/checkout", headers=self.headers[1], json=self.payload(1))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json["data"]["payments"][0]["qr_string"], "test-qr")
        self.assertEqual(response.json["data"]["payment_status"], "PENDING")
        self.gateway.fail = True
        response = self.client.post("/api/v1/web/checkout", headers=self.headers[1], json=self.payload(1))
        self.assertEqual(response.status_code, 503)
        self.assertIn("order_code", response.json["data"])
        self.assertNotIn("qr_image", response.json["data"]["payments"][0])
        self.assertEqual(response.json["data"]["payment_status"], "PENDING")

    def test_forward_skipped_duplicate_backward_and_terminal_transitions(self):
        self.assertEqual(self.status("PROCESSING").status_code, 400)
        self.pay()
        self.assertEqual(self.status("SHIPPED").status_code, 200)
        self.assertEqual(self.status("SHIPPED").status_code, 200)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(OrderStatusHistory)), 2)
        self.assertEqual(self.status("PROCESSING").status_code, 400)
        response = self.status("DELIVERED")
        self.assertEqual(response.status_code, 200)
        self.assertIsNotNone(response.json["data"]["delivered_at"])
        self.assertEqual(self.status("PENDING").status_code, 400)
        self.assertEqual(self.status("CANCELLED").status_code, 400)
        self.assertEqual(self.status("CONFIRMED").status_code, 400)
        response = self.client.patch(f"/api/v1/admin/orders/{self.id}/cancel", headers=self.headers[2], json={"reason": "No"})
        self.assertEqual(response.status_code, 400)

    def test_paid_flags_without_evidence_cannot_fulfill_and_manual_status_is_disabled(self):
        for model, id in ((Order, self.id), (Payment, self.ids["payment_id"]), (Invoice, self.ids["invoice_id"])):
            db.session.get(model, id).payment_status = "PAID"
        db.session.commit()
        self.assertEqual(self.status("DELIVERED").status_code, 400)
        for value in ("PAID", "REFUNDED", "PENDING", "CANCELLED"):
            response = self.client.patch(f"/api/v1/admin/orders/{self.id}/payment-status", headers=self.headers[2], json={"payment_status": value})
            self.assertEqual(response.status_code, 400)

    def test_customer_cancellation_pending_only_and_exactly_once(self):
        self.enable()
        PaymentService().initialize(self.ids["payment_id"])
        for _ in range(2):
            response = self.client.patch(f"/api/v1/web/orders/{self.id}/cancel", headers=self.headers[1], json={"reason": "Changed mind"})
            self.assertEqual(response.status_code, 200)
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement).where(StockMovement.reference_type == "ORDER_RETURN")), 1)
        self.assertEqual(self.status("PROCESSING").status_code, 400)

    def test_admin_cancel_actor_and_soft_deleted_order_late_payment_evidence(self):
        self.enable()
        PaymentService().initialize(self.ids["payment_id"])
        response = self.client.patch(f"/api/v1/admin/orders/{self.id}/cancel", headers=self.headers[2], json={"reason": "Admin cancellation"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"]["status_history"][-1]["changed_by"], 2)
        response = self.client.delete(f"/api/v1/admin/orders/{self.id}", headers=self.headers[2])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.get(f"/{self.id}").status_code, 404)
        self.gateway.status = "APPROVED"
        PaymentService().verify(self.ids["payment_id"])
        order = db.session.get(Order, self.id, populate_existing=True)
        self.assertTrue(order.is_deleted)
        self.assertEqual(order.order_status, "CANCELLED")
        self.assertEqual(order.payment_status, "PAID")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)

    def test_pending_delete_rejected_and_verified_delivered_delete_allowed(self):
        response = self.client.delete(f"/api/v1/admin/orders/{self.id}", headers=self.headers[2])
        self.assertEqual(response.status_code, 400)
        self.pay()
        self.assertEqual(self.status("DELIVERED").status_code, 200)
        self.assertEqual(self.client.delete(f"/api/v1/admin/orders/{self.id}", headers=self.headers[2]).status_code, 200)
        self.assertEqual(self.get("").json["pagination"]["total"], 0)

    def test_callback_ignores_unverified_status_and_limits_input(self):
        self.enable()
        PaymentService().initialize(self.ids["payment_id"])
        transaction = db.session.get(Payment, self.ids["payment_id"]).transaction_id
        def post(data):
            message = "".join(str(data[key]) for key in sorted(data))
            signature = base64.b64encode(hmac.new(b"test-callback-secret", message.encode(), hashlib.sha512).digest()).decode()
            return self.client.post("/testing/aba-callback", json=data,
                                    headers={"X-PayWay-HMAC-SHA512": signature})
        response = post({"tran_id": transaction, "status": "0", "payment_status": "PAID"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], [])
        self.assertEqual(db.session.get(Payment, self.ids["payment_id"], populate_existing=True).payment_status, "PENDING")
        self.gateway.status = "APPROVED"
        with patch.object(self.gateway, "verify", wraps=self.gateway.verify) as verify, \
                patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7) as notify:
            for _ in range(2):
                self.assertEqual(post({"tran_id": transaction}).status_code, 200)
            verify.assert_called_once()
            notify.assert_called_once()
        self.assertEqual(post({"tran_id": []}).status_code, 400)
        self.assertEqual(post({"tran_id": transaction, "padding": "x" * 17000}).status_code, 413)

    def test_concurrent_identical_status_requests_write_one_history(self):
        self.pay()
        barrier = Barrier(2)
        def worker():
            with self.app.test_request_context():
                barrier.wait(timeout=10)
                try:
                    return OrderService().update_status(self.id, "DELIVERED", "done", 2)["order_status"]
                finally:
                    db.session.remove()
        db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(results, ["DELIVERED", "DELIVERED"])
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(OrderStatusHistory)
            .where(OrderStatusHistory.new_status == "DELIVERED")), 1)


class OrderRouteRegistrationTests(unittest.TestCase):
    def test_application_keeps_existing_routes_and_registers_orders(self):
        from app import create_app
        # The test asserts code defaults, independent of operator environment.
        with patch("app.config.Config.PAYWAY_PUBLIC_API_ENABLED", False):
            app = create_app()
        paths = {rule.rule for rule in app.url_map.iter_rules()}
        for path in ("/api/v1/web/checkout", "/api/v1/admin/orders", "/api/v1/web/orders",
                     "/api/v1/admin/products", "/api/v1/admin/brands", "/api/v1/auth/login",
                     "/api/v1/web/delivery-methods"):
            self.assertIn(path, paths)
        self.assertFalse(app.config["PAYWAY_PUBLIC_API_ENABLED"])
