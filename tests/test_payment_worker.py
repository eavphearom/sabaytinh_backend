import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from flask import Flask

from app.extensions import db
from app.models import Payment, VariantStock, Order, StockMovement
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_state_service import PaymentStateService
from app.services.payments.public_payment_gate import require_public_payment_ready
from app.exceptions.api_exception import PaymentGatewayUnavailableException
from app.services.notifications.telegram_notification_service import TelegramNotificationService
from app.workers.payment_worker import PaymentWorker
from app.utils.date_util import DateUtil
from tests import test_payment_service as payment_tests


class WorkerConfigurationTests(unittest.TestCase):
    def test_invalid_settings_rejected(self):
        for key in ("PAYMENT_WORKER_INTERVAL_SECONDS", "PAYMENT_WORKER_BATCH_SIZE"):
            app = Flask(__name__)
            app.config[key] = 0
            with self.assertRaises(ValueError):
                PaymentWorker(app)

    def test_stop_and_cycle_error_recovery(self):
        worker = PaymentWorker(Flask(__name__))
        def fail():
            worker.stop.set()
            raise RuntimeError("private error")
        with patch.object(worker, "tick", side_effect=fail) as tick:
            self.assertEqual(worker.run(), 0)
            tick.assert_called_once()
        worker.stop.clear()
        with patch.object(worker, "tick", side_effect=RuntimeError()):
            self.assertEqual(worker.run(once=True), 1)

    def test_unverified_worker_blocks_public_gate(self):
        app = Flask(__name__)
        app.config.update(PAYWAY_PUBLIC_API_ENABLED=True, PAYWAY_CALLBACK_APPROVED=True,
                          PAYWAY_SANDBOX_VERIFIED=True, PAYWAY_WORKER_VERIFIED=False)
        with app.app_context(), self.assertRaises(PaymentGatewayUnavailableException):
            require_public_payment_ready()


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class WorkerPostgresTests(unittest.TestCase):
    setUpClass = classmethod(payment_tests.PaymentServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(payment_tests.PaymentServicePostgresTests.tearDownClass.__func__)
    tearDown = payment_tests.PaymentServicePostgresTests.tearDown
    payload = payment_tests.PaymentServicePostgresTests.payload
    payment = payment_tests.PaymentServicePostgresTests.payment

    def setUp(self):
        payment_tests.PaymentServicePostgresTests.setUp(self)
        self.app.config.update(PAYWAY_SANDBOX_ENABLED=True,
            PAYWAY_BASE_URL="https://checkout-sandbox.payway.com.kh",
            PAYWAY_API_KEY="test-key", PAYWAY_CALLBACK_URL="https://example.test/callback",
            TELEGRAM_BOT_TOKEN="", TELEGRAM_CHAT_ID="")
        PaymentService().initialize(self.payment_id)
        self.due()

    def due(self):
        self.payment().next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()

    def test_due_reconciliation_and_restart_no_duplicate(self):
        self.gateway.status = "APPROVED"
        with patch.object(TelegramNotificationService, "_send", return_value=7) as sender:
            result = PaymentWorker(self.app).tick()
            self.assertTrue(result["leader"])
            self.assertEqual(self.payment().payment_status, "PAID")
            db.session.remove()
            self.assertEqual(PaymentWorker(self.app).tick()["payments"], {})
            sender.assert_called_once()
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)

    def test_future_and_unscheduled_rows_are_skipped(self):
        for scheduled in (None, DateUtil.now() + timedelta(hours=1)):
            self.payment().next_check_at = scheduled
            db.session.commit()
            with patch.object(self.gateway, "verify") as verify:
                self.assertEqual(PaymentWorker(self.app).tick()["payments"], {})
                verify.assert_not_called()

    def test_transient_error_keeps_stock_and_retries_after_due(self):
        self.gateway.fail = True
        self.payment().expires_at = DateUtil.now() - timedelta(hours=1)
        db.session.commit()
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertGreater(self.payment().next_check_at, DateUtil.now())
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.gateway.fail = False
        self.gateway.status = "APPROVED"
        self.due()
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PAID")

    def test_expired_lease_recovers_after_restart(self):
        PaymentStateService().claim(self.payment_id, "verify")
        self.assertEqual(PaymentWorker(self.app).tick()["payments"], {})
        payment = self.payment()
        payment.gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        payment.next_check_at = payment.gateway_lease_until
        db.session.commit()
        db.session.remove()
        self.gateway.status = "APPROVED"
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PAID")

    def test_concurrent_worker_skips_and_lock_releases(self):
        started, release = Event(), Event()
        def work():
            started.set()
            self.assertTrue(release.wait(10))
            return {}
        first = PaymentWorker(self.app)
        with patch.object(first, "_payments", side_effect=work):
            with ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(first.tick)
                try:
                    self.assertTrue(started.wait(10))
                    self.assertEqual(PaymentWorker(self.app).tick(), {"leader": False})
                finally:
                    release.set()
                self.assertTrue(future.result(timeout=10)["leader"])
        self.assertTrue(PaymentWorker(self.app).tick()["leader"])

    def test_missing_sandbox_configuration_does_not_claim(self):
        self.app.config["PAYWAY_API_KEY"] = ""
        before = self.payment().next_check_at
        db.session.rollback()
        with patch.object(self.gateway, "verify") as verify:
            self.assertEqual(PaymentWorker(self.app).tick()["payments"], "not_configured")
            verify.assert_not_called()
        self.assertEqual(self.payment().next_check_at, before)
        self.assertIsNone(self.payment().gateway_lease_token)

    def test_telegram_retry_independent_of_gateway_config(self):
        with patch.object(TelegramNotificationService, "_send", side_effect=RuntimeError("test")):
            self.gateway.status = "APPROVED"
            PaymentService().verify(self.payment_id)
        self.app.config.update(PAYWAY_API_KEY="", TELEGRAM_BOT_TOKEN="123:test", TELEGRAM_CHAT_ID="123")
        with patch.object(TelegramNotificationService, "_send", return_value=7) as send:
            PaymentWorker(self.app).tick()
            send.assert_not_called()
            self.payment().gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
            db.session.commit()
            db.session.remove()
            self.assertEqual(PaymentWorker(self.app).tick()["telegram"], 1)
            PaymentWorker(self.app).tick()
            send.assert_called_once()
        self.assertEqual(self.payment().payment_status, "PAID")

    def test_old_record_retains_finances_for_manual_review(self):
        self.payment().created_at = DateUtil.now() - timedelta(days=8)
        db.session.commit()
        with patch.object(self.gateway, "verify") as verify:
            PaymentWorker(self.app).tick()
            verify.assert_not_called()
        self.assertIsNone(self.payment().next_check_at)
        self.assertIn("Manual review", self.payment().checkout_message)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)

    def test_unexpected_job_error_does_not_stop_other_job_or_hold_lock(self):
        worker = PaymentWorker(self.app)
        with patch.object(worker, "_payments", side_effect=RuntimeError("secret")), \
                patch.object(worker, "_telegram", return_value=0) as telegram:
            self.assertEqual(worker.tick()["payments"], "deferred")
            telegram.assert_called_once()
        self.assertTrue(PaymentWorker(self.app).tick()["leader"])

    def test_closure_and_worker_do_not_duplicate_stock_restoration(self):
        service = PaymentService()
        service.cancel(self.payment_id, 1, "Changed mind")
        PaymentWorker(self.app).tick()
        service.cancel(self.payment_id, 1, "Repeated request")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        self.assertEqual(len(db.session.scalars(db.select(StockMovement).where(
            StockMovement.reference_type == "ORDER_RETURN")).all()), 1)

    def test_late_payment_evidence_survives_worker(self):
        service = PaymentService()
        service.cancel(self.payment_id, 1, "Changed mind")
        transaction = self.payment().transaction_id
        db.session.rollback()
        self.gateway.status = "APPROVED"
        service.callback_hint(transaction)
        PaymentWorker(self.app).tick()
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(self.payment().gateway_state, "REFUND_REVIEW_NOTIFY_PENDING")
        self.assertEqual(db.session.get(Order, self.ids["order_id"]).order_status, "CANCELLED")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
