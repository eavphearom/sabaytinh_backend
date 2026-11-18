import os
import unittest
from datetime import timedelta
from unittest.mock import patch
from flask import Flask
from app.extensions import db
from app.models import Payment, VariantStock
from app.exceptions.api_exception import PaymentGatewayUnavailableException
from app.exceptions.handlers import register_error_handlers
from app.services.payments.payment_service import PaymentService
from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import GatewayError
from app.services.payments.public_payment_gate import require_public_payment_ready, require_callback_ready
from app.routes.v1.payway_callback_routes import register_payway_callback
from app.workers.payment_worker import PaymentWorker
from app.utils.date_util import DateUtil
from tests import test_payment_service as fixture


def config():
    return dict(PAYWAY_SANDBOX_ENABLED=True, PAYWAY_BASE_URL="https://checkout-sandbox.payway.com.kh",
        PAYWAY_MERCHANT_ID="test_merchant", PAYWAY_API_KEY="test-key",
        PAYWAY_CALLBACK_URL="", PAYWAY_CALLBACK_SECRET="", PAYWAY_CALLBACK_APPROVED=False,
        PAYWAY_PUBLIC_API_ENABLED=False, PAYWAY_SANDBOX_VERIFIED=False, PAYWAY_WORKER_VERIFIED=False,
        TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")


class CallbackIndependentGateTests(unittest.TestCase):
    def test_checkout_attestations_and_separate_callback_gate(self):
        app = Flask(__name__); app.config.update(config())
        with app.app_context():
            with self.assertRaises(PaymentGatewayUnavailableException): require_public_payment_ready()
            app.config.update(PAYWAY_PUBLIC_API_ENABLED=True, PAYWAY_SANDBOX_VERIFIED=True, PAYWAY_WORKER_VERIFIED=True)
            require_public_payment_ready()
            with self.assertRaises(PaymentGatewayUnavailableException): require_callback_ready()
            for key in ("PAYWAY_PUBLIC_API_ENABLED", "PAYWAY_SANDBOX_VERIFIED", "PAYWAY_WORKER_VERIFIED"):
                app.config[key] = False
                with self.assertRaises(PaymentGatewayUnavailableException): require_public_payment_ready()
                app.config[key] = True

    def test_callback_missing_secret_and_unapproved_remain_disabled(self):
        app = Flask(__name__); app.config.update(config())
        register_error_handlers(app)
        register_payway_callback(app)
        self.assertNotIn("payway_callback_path", app.extensions)
        app.config.update(PAYWAY_CALLBACK_URL="https://example.test/callback",
            PAYWAY_PUBLIC_API_ENABLED=True, PAYWAY_SANDBOX_VERIFIED=True, PAYWAY_WORKER_VERIFIED=True)
        register_payway_callback(app)
        for approved, secret in ((False, "test-secret"), (True, "")):
            app.config.update(PAYWAY_CALLBACK_APPROVED=approved, PAYWAY_CALLBACK_SECRET=secret)
            with patch.object(PaymentService, "callback_hint") as hint:
                self.assertEqual(app.test_client().post("/callback", json={"status": "0"}).status_code, 503)
                hint.assert_not_called()


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class CallbackIndependentPaymentTests(unittest.TestCase):
    setUpClass = classmethod(fixture.PaymentServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(fixture.PaymentServicePostgresTests.tearDownClass.__func__)
    tearDown = fixture.PaymentServicePostgresTests.tearDown
    payload = fixture.PaymentServicePostgresTests.payload
    payment = fixture.PaymentServicePostgresTests.payment

    def setUp(self):
        fixture.PaymentServicePostgresTests.setUp(self)
        self.strategy_patch.stop()  # Exercise the real factory, strategy and client.
        self.app.config.update(config())
        self.amount = self.payment().amount
        db.session.rollback()
        self.status = "PENDING"
        self.fail = False
        self.calls = []
        self.post_patch = patch.object(PayWayClient, "_post", side_effect=self.post)
        self.post_patch.start(); self.addCleanup(self.post_patch.stop)

    def post(self, path, payload):
        self.assertFalse(db.session().in_transaction())
        self.calls.append((path, dict(payload)))
        if self.fail: raise GatewayError("Mock timeout")
        if path == PayWayClient.QR_PATH:
            self.assertNotIn("callback_url", payload)
            return dict(status={"code": "0"}, amount=self.amount, currency="USD", qrString="test-qr",
                qrImage="data:image/png;base64,dGVzdA==", abapay_deeplink="abamobilebank://test")
        if path == PayWayClient.CLOSE_PATH:
            return {"status": {"code": "00", "tran_id": payload["tran_id"]}}
        return {"status": {"code": "00", "tran_id": payload["tran_id"]}, "data": {
            "original_amount": self.amount, "total_amount": self.amount, "payment_amount": self.amount,
            "payment_currency": "USD", "payment_status": self.status,
            "payment_status_code": 0 if self.status == "APPROVED" else 2, "refund_amount": 0,
            "apv": "test-approval" if self.status == "APPROVED" else ""}}

    def due(self):
        self.payment().next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()

    def test_worker_settles_without_callbacks_and_duplicate_check_is_idempotent(self):
        PaymentService().initialize(self.payment_id)
        self.status = "APPROVED"; self.due()
        with patch("app.services.notifications.telegram_notification_service.TelegramNotificationService.notify_verified_payment") as hook:
            PaymentWorker(self.app).tick()
            PaymentService().verify(self.payment_id)
            self.assertEqual(hook.call_count, 1)
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(sum(path == PayWayClient.CHECK_PATH for path, _ in self.calls), 1)
        self.assertFalse(self.app.config["PAYWAY_PUBLIC_API_ENABLED"])

    def test_timeout_preserves_transaction_then_new_worker_recovers(self):
        self.fail = True
        with self.assertRaises(GatewayError): PaymentService().initialize(self.payment_id)
        transaction_id = self.payment().transaction_id
        self.assertTrue(transaction_id)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.due(); PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.fail = False; self.status = "APPROVED"; self.due(); db.session.remove()
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(self.payment().transaction_id, transaction_id)
        self.assertEqual(sum(path == PayWayClient.QR_PATH for path, _ in self.calls), 1)

    def test_expired_lease_and_qr_recover_without_releasing_stock(self):
        PaymentService().initialize(self.payment_id)
        payment = self.payment()
        payment.gateway_lease_token = "crashed-worker"
        payment.gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        payment.expires_at = DateUtil.now() - timedelta(minutes=1)
        self.due(); db.session.remove()
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        db.session.rollback()
        PaymentService().cancel(self.payment_id, 1, "Sandbox cleanup")
        PaymentService().cancel(self.payment_id, 1, "Sandbox cleanup")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        self.assertEqual(sum(path == PayWayClient.CLOSE_PATH for path, _ in self.calls), 1)

    def test_amount_mismatch_never_settles(self):
        PaymentService().initialize(self.payment_id)
        self.amount += 1; self.status = "APPROVED"; self.due()
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
