from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import timedelta
import os
from threading import Barrier
import unittest
from unittest.mock import patch

import sqlalchemy as sa

from app.extensions import db
from app.models import Order, Payment, Invoice, VariantStock, StockMovement, OrderStatusHistory
from app.exceptions.api_exception import BadRequestException
from app.services.checkout_service import CheckoutService
from app.services.payments.payment_strategy import GatewayError, GatewayResult
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_state_service import PaymentStateService
from app.utils.date_util import DateUtil
from tests import test_checkout_service as checkout_tests


class MockGateway:
    """Gateway evidence only for tests; never installed in application code."""
    status = "PENDING"
    fail = False
    def evidence(self, context, status):
        assert not db.session().in_transaction(), "HTTP attempted inside database transaction"
        if self.fail:
            raise GatewayError("Mock timeout")
        return GatewayResult(context.transaction_id, context.merchant_id,
                             context.amount, context.currency, status,
                             reference="test-approval" if status == "APPROVED" else None)
    def initialize(self, context):
        return replace(self.evidence(context, "READY"), qr_string="test-qr",
                       qr_image="data:image/png;base64,dGVzdA==", abapay_deeplink="abamobilebank://test",
                       expires_at=DateUtil.now() + timedelta(minutes=15))
    def verify(self, context):
        return self.evidence(context, self.status)
    def close(self, context):
        return self.evidence(context, "CLOSED")


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class PaymentServicePostgresTests(unittest.TestCase):
    setUpClass = classmethod(checkout_tests.CheckoutServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(checkout_tests.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = checkout_tests.CheckoutServicePostgresTests.tearDown
    payload = checkout_tests.CheckoutServicePostgresTests.payload

    def setUp(self):
        checkout_tests.CheckoutServicePostgresTests.setUp(self)
        self.app.config.update(PAYWAY_MERCHANT_ID="test_merchant", PAYWAY_LEASE_SECONDS=90)
        self.gateway = MockGateway()
        self.gateway.status = "PENDING"
        self.gateway.fail = False
        self.strategy_patch = patch(
            "app.services.payments.payment_service.PaymentStrategyFactory.resolve", return_value=self.gateway)
        self.strategy_patch.start()
        self.addCleanup(self.strategy_patch.stop)
        self.ids = CheckoutService().checkout(1, self.payload())
        self.payment_id = self.ids["payment_id"]

    def payment(self):
        return db.session.get(Payment, self.payment_id, populate_existing=True)

    def test_initialize_persists_qr_but_not_image_or_secrets(self):
        response = PaymentService().initialize(self.payment_id)
        self.assertEqual(response["qr_image"], "data:image/png;base64,dGVzdA==")
        self.assertEqual(response["payment_status"], "PENDING")
        self.assertNotIn("gateway_lease_token", response)
        payment = self.payment()
        self.assertEqual(payment.qr_string, "test-qr")
        self.assertEqual(len(payment.transaction_id), 20)
        self.assertNotIn("qr_image", Payment.__table__.columns)
        with self.assertRaises(BadRequestException):
            PaymentService().initialize(self.payment_id)

    def test_paid_duplicate_callbacks_and_after_commit_hook(self):
        PaymentService().initialize(self.payment_id)
        transaction = self.payment().transaction_id
        db.session.rollback()
        self.gateway.status = "APPROVED"
        events = []
        def hook(event):
            self.assertFalse(db.session().in_transaction())
            events.append(event)
        service = PaymentService(paid_hook=hook)
        service.callback_hint(transaction)
        service.callback_hint(transaction)
        service.verify(self.payment_id)
        self.assertEqual(len(events), 1)
        self.assertEqual(self.payment().payment_status, "PAID")
        order = db.session.get(Order, self.ids["order_id"])
        invoice = db.session.get(Invoice, self.ids["invoice_id"])
        self.assertEqual((order.payment_status, invoice.payment_status), ("PAID", "PAID"))
        self.assertIsNotNone(invoice.paid_at)
        self.assertIsNotNone(self.payment().paid_at)

    def test_timeouts_and_expired_qr_do_not_restore_stock(self):
        self.gateway.fail = True
        with self.assertRaises(GatewayError):
            PaymentService().initialize(self.payment_id)
        payment = self.payment()
        self.assertIsNotNone(payment.transaction_id)
        self.assertEqual(payment.gateway_state, "RECONCILE_REQUIRED")
        payment.expires_at = DateUtil.now() - timedelta(minutes=1)
        payment.next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        self.gateway.fail = False
        PaymentService().reconcile_due()
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.assertEqual(self.payment().payment_status, "PENDING")

    def test_cancellation_restores_once_and_late_success_flags_review(self):
        service = PaymentService()
        service.initialize(self.payment_id)
        service.cancel(self.payment_id, 1, "Changed mind")
        service.cancel(self.payment_id, 1, "Repeated request")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        returns = db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement).where(StockMovement.reference_type == "ORDER_RETURN"))
        self.assertEqual(returns, 1)
        self.gateway.status = "APPROVED"
        service.verify(self.payment_id)
        self.assertEqual(db.session.get(Order, self.ids["order_id"], populate_existing=True).order_status, "CANCELLED")
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(self.payment().gateway_state, "REFUND_REVIEW_NOTIFY_PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)

    def test_cancellation_requires_closed_gateway_and_customer_ownership(self):
        service = PaymentService()
        service.initialize(self.payment_id)
        with self.assertRaises(BadRequestException):
            service.cancel(self.payment_id, 2, "Not my order")
        with patch.object(self.gateway, "close", side_effect=GatewayError("Timeout")):
            with self.assertRaises(GatewayError):
                service.cancel(self.payment_id, 1, "Changed mind")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.gateway.status = "APPROVED"
        service.cancel(self.payment_id, 1, "Too late")
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)

    def test_mismatched_evidence_cannot_mark_paid(self):
        service = PaymentService()
        service.initialize(self.payment_id)
        for field, value in (("transaction_id", "other"), ("currency", "KHR"), ("merchant_id", "other")):
            def mismatch(context):
                return replace(self.gateway.evidence(context, "APPROVED"), **{field: value})
            with patch.object(self.gateway, "verify", side_effect=mismatch):
                with self.assertRaises(GatewayError):
                    service.verify(self.payment_id)
            self.assertEqual(self.payment().payment_status, "PENDING")

    def test_financial_update_failure_rolls_back(self):
        service = PaymentService()
        service.initialize(self.payment_id)
        self.gateway.status = "APPROVED"
        # Fail at the actual flush of financial state, after lease commit.
        def reject(session, flush_context, instances):
            if any(isinstance(obj, Payment) and obj.payment_status == "PAID" for obj in session.dirty):
                raise RuntimeError("Injected financial failure")
        sa.event.listen(db.session(), "before_flush", reject)
        try:
            with self.assertRaisesRegex(RuntimeError, "financial failure"):
                service.verify(self.payment_id)
        finally:
            sa.event.remove(db.session(), "before_flush", reject)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(Order, self.ids["order_id"]).payment_status, "PENDING")
        self.assertEqual(db.session.get(Invoice, self.ids["invoice_id"]).payment_status, "PENDING")

    def test_concurrent_verification_uses_one_fenced_lease(self):
        PaymentService().initialize(self.payment_id)
        barrier = Barrier(2)
        def worker():
            with self.app.app_context():
                barrier.wait(timeout=10)
                try:
                    return PaymentStateService().claim(self.payment_id, "verify")
                except BadRequestException:
                    return None
                finally:
                    db.session.remove()
        db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(sum(result is not None for result in results), 1)
        context = next(result for result in results if result is not None)
        payment = self.payment()
        payment.gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        replacement = PaymentStateService().claim(self.payment_id, "verify")
        with self.assertRaises(BadRequestException):
            PaymentStateService().apply(context, self.gateway.evidence(context, "APPROVED"), "verify")
        PaymentStateService().apply(replacement, self.gateway.evidence(replacement, "APPROVED"), "verify")
        self.assertEqual(self.payment().payment_status, "PAID")

    def test_notification_marker_survives_failure_and_retries(self):
        service = PaymentService(paid_hook=lambda event: (_ for _ in ()).throw(RuntimeError("hook failure")))
        service.initialize(self.payment_id)
        self.gateway.status = "APPROVED"
        service.verify(self.payment_id)
        payment = self.payment()
        self.assertEqual(payment.gateway_state, "PAID_NOTIFY_PENDING")
        payment.gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        events = []
        state = PaymentStateService(paid_hook=events.append)
        self.assertEqual(state.dispatch_pending_notifications(), 1)
        self.assertEqual(state.dispatch_pending_notifications(), 0)
        self.assertEqual(len(events), 1)

    def test_failed_cancellation_state_update_rolls_back_stock_restoration(self):
        service = PaymentService()
        service.initialize(self.payment_id)
        def reject(session, flush_context, instances):
            if any(isinstance(obj, OrderStatusHistory) and obj.new_status == "CANCELLED" for obj in session.new):
                raise RuntimeError("Injected cancellation failure")
        sa.event.listen(db.session(), "before_flush", reject)
        try:
            with self.assertRaisesRegex(RuntimeError, "cancellation failure"):
                service.cancel(self.payment_id, 1, "Changed mind")
        finally:
            sa.event.remove(db.session(), "before_flush", reject)
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
        self.assertEqual(db.session.get(Order, self.ids["order_id"]).order_status, "PENDING")
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement)
            .where(StockMovement.reference_type == "ORDER_RETURN")), 0)

    def test_concurrent_cancellation_restores_stock_once(self):
        PaymentService().initialize(self.payment_id)
        barrier = Barrier(2)
        def worker():
            with self.app.app_context():
                barrier.wait(timeout=10)
                try:
                    return PaymentService().cancel(self.payment_id, 1, "Changed mind")
                except BadRequestException:
                    return None
                finally:
                    db.session.remove()
        db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            list(pool.map(lambda _: worker(), range(2)))
        self.assertEqual(db.session.get(VariantStock, 1).qty, 5)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement)
            .where(StockMovement.reference_type == "ORDER_RETURN")), 1)
