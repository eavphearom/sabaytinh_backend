import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from sqlalchemy import select, func

from app.extensions import db
from app.models import Order, Payment, Invoice, VariantStock, StockMovement
from app.services.order_service import OrderService
from app.services.payments.payment_service import PaymentService
from app.utils.date_util import DateUtil
from tests import test_order_routes as route_tests


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class ResumePostgresTests(unittest.TestCase):
    setUpClass = classmethod(route_tests.OrderAPIPostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(route_tests.OrderAPIPostgresTests.tearDownClass.__func__)
    setUp = route_tests.OrderAPIPostgresTests.setUp
    tearDown = route_tests.OrderAPIPostgresTests.tearDown
    payload = route_tests.OrderAPIPostgresTests.payload
    enable = route_tests.OrderAPIPostgresTests.enable
    pay = route_tests.OrderAPIPostgresTests.pay

    def resume(self, user=1):
        return self.client.post(f"/api/v1/web/orders/{self.id}/payment/resume", headers=self.headers[user])

    def initialize(self):
        self.enable()
        PaymentService().initialize(self.ids["payment_id"])

    def assert_unchanged_inventory(self):
        self.assertEqual(db.session.scalar(select(func.count()).select_from(Order)), 1)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(Payment)), 1)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(StockMovement)), 1)
        self.assertEqual(db.session.get(VariantStock, 1, populate_existing=True).qty, 3)

    def test_valid_saved_qr_reused_and_duplicates_do_not_initialize(self):
        self.initialize()
        transaction = db.session.get(Payment, self.ids["payment_id"]).transaction_id
        db.session.rollback()
        with patch.object(self.gateway, "initialize") as initialize, patch.object(self.gateway, "verify") as verify:
            for _ in range(2):
                response = self.resume()
                self.assertEqual(response.status_code, 200)
                data = response.json["data"]
                self.assertEqual(data["order_id"], self.id)
                self.assertEqual(data["payment"]["checkout_status"], "READY")
                self.assertEqual(data["payment"]["transaction_id"], transaction)
                self.assertEqual(data["payment"]["qr_string"], "test-qr")
                self.assertEqual(data["payment"]["qr_image"], "data:image/png;base64,dGVzdA==")
                self.assertNotIn("gateway_lease_token", data["payment"])
            initialize.assert_not_called()
            verify.assert_not_called()
        self.assert_unchanged_inventory()

    def test_old_payment_without_image_keeps_qr_fallback(self):
        self.initialize()
        payment = db.session.get(Payment, self.ids["payment_id"])
        payment.qr_image = None
        db.session.commit()
        db.session.remove()
        with patch.object(self.gateway, "initialize") as initialize, patch.object(self.gateway, "verify") as verify:
            response = self.resume()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"]["payment"]["qr_string"], "test-qr")
            self.assertNotIn("qr_image", response.json["data"]["payment"])
            initialize.assert_not_called()
            verify.assert_not_called()
        self.assert_unchanged_inventory()

    def test_saved_image_not_exposed_to_another_customer(self):
        self.initialize()
        db.session.remove()
        for endpoint in (f"/api/v1/web/orders/{self.id}", f"/api/v1/web/orders/{self.id}/payment/resume"):
            method = self.client.post if endpoint.endswith("resume") else self.client.get
            response = method(endpoint, headers=self.headers[3])
            self.assertEqual(response.status_code, 404)
            self.assertNotIn("data:image", response.get_data(as_text=True))

    def test_paid_returns_verified_status_without_gateway(self):
        self.enable()
        self.pay()
        with patch.object(self.gateway, "initialize") as initialize, patch.object(self.gateway, "verify") as verify:
            response = self.resume()
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json["data"]["payment"]["payment_status"], "PAID")
            self.assertNotIn("qr_string", response.json["data"]["payment"])
            initialize.assert_not_called()
            verify.assert_not_called()
        self.assert_unchanged_inventory()

    def test_expired_qr_verifies_and_settles_without_inventory_changes(self):
        self.initialize()
        db.session.get(Payment, self.ids["payment_id"]).expires_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        self.gateway.status = "APPROVED"
        with patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7) as send:
            response = self.resume()
            self.assertEqual(response.json["data"]["payment"]["payment_status"], "PAID")
            self.resume()
            send.assert_called_once()
        self.assertEqual(db.session.get(Invoice, self.ids["invoice_id"]).payment_status, "PAID")
        self.assert_unchanged_inventory()

    def test_expired_unconfirmed_close_never_returns_qr(self):
        self.initialize()
        db.session.get(Payment, self.ids["payment_id"]).expires_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        self.gateway.close = lambda ctx: self.gateway.evidence(ctx, "PENDING")
        for fail in (False, True):
            self.gateway.fail = fail
            response = self.resume()
            self.assertEqual(response.status_code, 200)
            payment = response.json["data"]["payment"]
            self.assertEqual(payment["payment_status"], "PENDING")
            self.assertEqual(payment["checkout_status"], "RECONCILIATION_REQUIRED")
            self.assertNotIn("qr_string", payment)
            self.assertNotIn("qr_image", payment)
            self.assertNotIn("abapay_deeplink", payment)
            self.assertIn("replacement QR is unavailable", payment["checkout_message"])
        self.assert_unchanged_inventory()

    def test_busy_and_never_initialized_payments_do_not_start_gateway_calls(self):
        self.enable()
        with patch.object(self.gateway, "initialize") as initialize, patch.object(self.gateway, "verify") as verify:
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
            payment = db.session.get(Payment, self.ids["payment_id"])
            payment.transaction_id = "existing"
            payment.gateway_lease_until = DateUtil.now() + timedelta(seconds=60)
            db.session.commit()
            self.assertIn("in progress", self.resume().json["data"]["payment"]["checkout_message"])
            initialize.assert_not_called()
            verify.assert_not_called()

    def test_auth_ownership_deleted_cancelled_and_disabled_gate(self):
        self.assertEqual(self.client.post(f"/api/v1/web/orders/{self.id}/payment/resume").status_code, 401)
        self.assertEqual(self.resume().status_code, 503)
        self.enable()
        self.assertEqual(self.resume(user=3).status_code, 404)
        order = db.session.get(Order, self.id)
        order.order_status = "CANCELLED"
        db.session.commit()
        self.assertEqual(self.resume().status_code, 400)
        db.session.get(Order, self.id).is_deleted = True
        db.session.commit()
        self.assertEqual(self.resume().status_code, 404)
        self.assert_unchanged_inventory()

    def test_inconsistent_finances_and_unverified_paid_rejected(self):
        self.enable()
        invoice = db.session.get(Invoice, self.ids["invoice_id"])
        invoice.total_amount += 1
        db.session.commit()
        self.assertEqual(self.resume().status_code, 400)
        db.session.get(Invoice, self.ids["invoice_id"]).total_amount -= 1
        for model, id in ((Order, self.id), (Payment, self.ids["payment_id"]), (Invoice, self.ids["invoice_id"])):
            db.session.get(model, id).payment_status = "PAID"
        db.session.commit()
        self.assertEqual(self.resume().status_code, 400)

    def test_concurrent_resume_reuses_one_attempt(self):
        self.initialize()
        barrier = Barrier(2)
        def resume():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return OrderService().resume_payment(self.id, 1)
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: resume(), range(2)))
        self.assertEqual(results[0], results[1])
        self.assert_unchanged_inventory()
