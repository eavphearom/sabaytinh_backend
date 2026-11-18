"""Real PostgreSQL locking/transactions, mocked gateway only."""
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Event
from unittest.mock import patch

from sqlalchemy import select, func

from app.extensions import db
from app.models import Order, Payment, Invoice, StockMovement, VariantStock
from app.services.order_service import OrderService
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_strategy import GatewayError
from app.utils.date_util import DateUtil
from tests import test_payment_resume as resume_tests


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class RenewalTests(unittest.TestCase):
    setUpClass = classmethod(resume_tests.ResumePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(resume_tests.ResumePostgresTests.tearDownClass.__func__)
    tearDown = resume_tests.ResumePostgresTests.tearDown
    payload = resume_tests.ResumePostgresTests.payload
    enable = resume_tests.ResumePostgresTests.enable
    resume = resume_tests.ResumePostgresTests.resume
    initialize = resume_tests.ResumePostgresTests.initialize

    def setUp(self):
        resume_tests.ResumePostgresTests.setUp(self)
        self.initialize()
        self.old_id = self.ids["payment_id"]
        old = db.session.get(Payment, self.old_id)
        self.old_transaction = old.transaction_id
        old.expires_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        self.closed = False
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "CANCELLED" if self.closed else "PENDING")
        def close(ctx):
            result = self.gateway.evidence(ctx, "CLOSED")
            self.closed = True
            return result
        self.gateway.close = close

    def assert_preserved(self, count=2):
        db.session.expire_all()
        for model in (Order, Invoice, StockMovement):
            self.assertEqual(db.session.scalar(select(func.count()).select_from(model)), 1)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(Payment)), count)
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.assertEqual(str(db.session.get(Order, self.id).total_amount), "21.50")
        self.assertEqual(db.session.get(Payment, self.old_id).transaction_id, self.old_transaction)
        db.session.rollback()

    def test_confirmed_renewal_persists_image_and_duplicate_reuses_it(self):
        with patch.object(self.gateway, "initialize", wraps=self.gateway.initialize) as initialize:
            response = self.resume()
            self.assertEqual(response.status_code, 200)
            payment = response.json["data"]["payment"]
            self.assertNotEqual(payment["id"], self.old_id)
            self.assertNotEqual(payment["transaction_id"], self.old_transaction)
            self.assertEqual(payment["checkout_status"], "READY")
            self.assertEqual(payment["qr_image"], "data:image/png;base64,dGVzdA==")
            db.session.remove()
            self.assertEqual(self.resume().json["data"]["payment"], payment)
            initialize.assert_called_once()
        old = db.session.get(Payment, self.old_id)
        self.assertEqual(old.payment_status, "CANCELLED")
        self.assertIsNotNone(old.close_accepted_at)
        self.assertIsNotNone(old.closure_verified_at)
        self.assertEqual(db.session.get(Payment, payment["id"]).replaces_payment_id, self.old_id)
        self.assert_preserved()

    def test_close_success_pending_creates_one_replacement(self):
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "PENDING")
        with patch.object(self.gateway, "close", wraps=self.gateway.close) as close:
            first = self.resume().json["data"]["payment"]
            self.assertEqual(first["checkout_status"], "READY")
            db.session.remove()
            self.assertEqual(self.resume().json["data"]["payment"], first)
            close.assert_called_once()
        self.assertIn("post-close check PENDING", db.session.get(Payment, self.old_id).checkout_message)
        self.assert_preserved()

    def test_post_close_timeout_restart_rechecks_without_repeating_close(self):
        def verify(ctx):
            if self.closed:
                raise GatewayError("Mock timeout")
            return self.gateway.evidence(ctx, "PENDING")
        self.gateway.verify = verify
        with patch.object(self.gateway, "close", wraps=self.gateway.close) as close:
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
            self.assert_preserved(count=1)
            db.session.remove()
            self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "PENDING")
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "READY")
            close.assert_called_once()
        self.assert_preserved()

    def test_pending_without_close_evidence_cannot_replace(self):
        from app.exceptions.api_exception import BadRequestException
        service = PaymentService()
        context = service.state.claim(self.old_id, "renew", 1)
        with self.assertRaises(BadRequestException):
            service.state.replace_closed_attempt(context, self.gateway.evidence(context, "PENDING"), 1)
        self.assert_preserved(count=1)

    def test_check_and_close_failures_keep_only_old_attempt(self):
        for method in ("verify", "close"):
            with self.subTest(method=method), patch.object(self.gateway, method, side_effect=GatewayError("Mock timeout")):
                payment = self.resume().json["data"]["payment"]
                self.assertEqual(payment["checkout_status"], "RECONCILIATION_REQUIRED")
                self.assertNotIn("qr_image", payment)
                self.assert_preserved(count=1)

    def test_approval_racing_close_settles_without_replacement(self):
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "APPROVED" if self.closed else "PENDING")
        with patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7) as send:
            response = self.resume()
            self.assertEqual(response.json["data"]["payment"]["payment_status"], "PAID")
            self.resume()
            send.assert_called_once()
        self.assert_preserved(count=1)

    def test_unconfirmed_close_or_mismatched_evidence_cannot_renew(self):
        from dataclasses import replace
        for invalid in ("PENDING", "bad_transaction"):
            def close(ctx):
                result = self.gateway.evidence(ctx, "CLOSED" if invalid == "bad_transaction" else invalid)
                return replace(result, transaction_id="wrong") if invalid == "bad_transaction" else result
            with self.subTest(invalid=invalid), patch.object(self.gateway, "close", side_effect=close):
                self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
                self.assertIsNone(db.session.get(Payment, self.old_id).close_accepted_at)
                self.assert_preserved(count=1)

    def test_old_transaction_outside_check_window_requires_review(self):
        db.session.get(Payment, self.old_id).created_at = DateUtil.now() - timedelta(days=8)
        db.session.commit()
        with patch.object(self.gateway, "verify") as verify, patch.object(self.gateway, "close") as close:
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
            verify.assert_not_called()
            close.assert_not_called()
        self.assert_preserved(count=1)

    def test_new_initialization_timeout_preserves_new_id_and_worker_recovers(self):
        with patch.object(self.gateway, "initialize", side_effect=GatewayError("Mock timeout")) as initialize:
            payment = self.resume().json["data"]["payment"]
            self.assertNotEqual(payment["id"], self.old_id)
            self.assertEqual(payment["checkout_status"], "RECONCILIATION_REQUIRED")
            initialize.assert_called_once()
        new_id = payment["id"]
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "APPROVED" if ctx.payment_id == new_id else "CANCELLED")
        db.session.get(Payment, new_id).next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()
        events = []
        with patch.object(self.gateway, "initialize") as initialize:
            PaymentService(paid_hook=events.append).reconcile_due()
            PaymentService(paid_hook=events.append).verify(new_id)
            initialize.assert_not_called()
        self.assertEqual(len(events), 1)
        for model, id in ((Order, self.id), (Invoice, self.ids["invoice_id"]), (Payment, new_id)):
            self.assertEqual(db.session.get(model, id).payment_status, "PAID")
        self.assert_preserved()

    def test_concurrent_requests_cannot_create_competing_attempts(self):
        entered, release = Event(), Event()
        original = self.gateway.verify
        def verify(ctx):
            entered.set()
            if not release.wait(10):
                raise AssertionError("Test synchronization timed out")
            return original(ctx)
        self.gateway.verify = verify
        def resume():
            with self.app.app_context():
                return OrderService().resume_payment(self.id, 1)
        with patch.object(self.gateway, "initialize", wraps=self.gateway.initialize) as initialize:
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(resume)
                try:
                    self.assertTrue(entered.wait(10))
                    second = pool.submit(resume).result(timeout=10)
                    self.assertEqual(second["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
                finally:
                    release.set()
                self.assertEqual(first.result(timeout=10)["payment"]["checkout_status"], "READY")
            initialize.assert_called_once()
        self.assert_preserved()

    def test_historical_approval_recorded_for_review_without_second_notification(self):
        new_id = self.resume().json["data"]["payment"]["id"]
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "APPROVED")
        events = []
        service = PaymentService(paid_hook=events.append)
        service.verify(new_id)
        service.verify(self.old_id)
        service.verify(self.old_id)
        self.assertEqual(len(events), 1)
        old = db.session.get(Payment, self.old_id)
        self.assertEqual(old.payment_status, "PAID")
        self.assertEqual(old.gateway_state, "REFUND_REVIEW")
        self.assertEqual(old.payment_reference, "test-approval")
        db.session.rollback()
        self.assertEqual(self.resume().status_code, 400)
        self.assert_preserved()

    def test_historical_approval_before_current_blocks_qr_and_fulfillment(self):
        new_id = self.resume().json["data"]["payment"]["id"]
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "APPROVED")
        events = []
        service = PaymentService(paid_hook=events.append)
        service.verify(self.old_id)
        self.assertEqual(self.resume().status_code, 400)
        service.verify(new_id)
        self.assertEqual(events, [])
        self.assertEqual(db.session.get(Payment, new_id).gateway_state, "REFUND_REVIEW")
        self.assert_preserved()

    def test_cancellation_after_renewal_restores_only_once(self):
        new_id = self.resume().json["data"]["payment"]["id"]
        service = PaymentService(paid_hook=lambda event: None)
        service.cancel(new_id, 1, "Changed mind")
        service.cancel(new_id, 1, "Changed mind")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        self.assertEqual(db.session.scalar(select(func.count()).select_from(StockMovement)), 2)
        self.assertEqual(db.session.get(Order, self.id).order_status, "CANCELLED")

    def test_committed_initialization_lease_restart_never_reinitializes(self):
        service = PaymentService(paid_hook=lambda event: None)
        context = service.state.claim(self.old_id, "renew", 1)
        service.state.record_close_acceptance(context, self.gateway.close(context))
        new_context = service.state.replace_closed_attempt(context, self.gateway.verify(context), 1)
        payment = db.session.get(Payment, new_context.payment_id)
        payment.gateway_lease_until = payment.next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "PENDING")
        with patch.object(self.gateway, "initialize") as initialize:
            PaymentService().reconcile_due()
            PaymentService().reconcile_due()
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "RECONCILIATION_REQUIRED")
            initialize.assert_not_called()
        self.assert_preserved()

    def test_expired_lease_cannot_replace_payment(self):
        from app.exceptions.api_exception import BadRequestException
        service = PaymentService()
        context = service.state.claim(self.old_id, "renew", 1)
        service.state.record_close_acceptance(context, self.gateway.close(context))
        result = self.gateway.verify(context)
        db.session.get(Payment, self.old_id).gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        with self.assertRaises(BadRequestException):
            service.state.replace_closed_attempt(context, result, 1)
        self.assert_preserved(count=1)
        # A fresh process/lease can finish verified closure without repeating Close.
        with patch.object(self.gateway, "close") as close:
            self.assertEqual(self.resume().json["data"]["payment"]["checkout_status"], "READY")
            close.assert_not_called()
        self.assert_preserved()

    def test_historical_closed_attempt_remains_due_for_verification(self):
        self.resume()
        old = db.session.get(Payment, self.old_id)
        old.next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        events = []
        self.gateway.verify = lambda ctx: self.gateway.evidence(ctx, "APPROVED")
        results = PaymentService(paid_hook=events.append).reconcile_due()
        self.assertIn(self.old_id, results)
        self.assertEqual(db.session.get(Payment, self.old_id).gateway_state, "REFUND_REVIEW")
        self.assertEqual(events, [])
        self.assert_preserved()
