import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from threading import Barrier
from unittest.mock import patch

from flask import Flask

from app.extensions import db
from app.models import Payment, Order, Invoice, OrderItem
from app.services.notifications.telegram_notification_service import (
    NotificationDeliveryError, TelegramNotificationService,
)
from app.services.payments.payment_service import PaymentService
from app.services.payments.payment_state_service import PaymentStateService
from app.utils.date_util import DateUtil
from tests import test_payment_service as payment_tests


class TelegramTransportTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(TELEGRAM_BOT_TOKEN="123:test-secret", TELEGRAM_CHAT_ID="-100123")
        self.context = app.app_context()
        self.context.push()
        self.addCleanup(self.context.pop)
        self.app = app
        self.service = TelegramNotificationService()
        self.transport = patch("app.services.notifications.telegram_notification_service.http.client.HTTPSConnection")
        self.factory = self.transport.start()
        self.addCleanup(self.transport.stop)
        self.connection = self.factory.return_value
        self.response = self.connection.getresponse.return_value
        self.response.status = 200
        self.response.read.return_value = b'{"ok":true,"result":{"message_id":7}}'

    def test_https_plain_text_success(self):
        self.assertEqual(self.service._send("<b>Product</b> *test* & x2"), 7)
        self.assertEqual(self.factory.call_args.args, ("api.telegram.org",))
        payload = json.loads(self.connection.request.call_args.kwargs["body"])
        self.assertNotIn("parse_mode", payload)
        self.assertEqual(payload["text"], "<b>Product</b> *test* & x2")
        self.connection.close.assert_called_once()

    def test_missing_credentials_does_not_connect(self):
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            with patch.dict(self.app.config, {key: ""}):
                with self.assertRaises(NotificationDeliveryError):
                    self.service._send("test")
        self.factory.assert_not_called()

    def test_rate_limit_uses_retry_after(self):
        self.response.status = 429
        self.response.read.return_value = b'{"ok":false,"parameters":{"retry_after":3600}}'
        with self.assertRaises(NotificationDeliveryError) as caught:
            self.service._send("test")
        self.assertEqual(caught.exception.retry_after, 3600)

    def test_http_and_protocol_errors_are_sanitized(self):
        for status, body in ((401, b'{"ok":false,"description":"123:test-secret"}'),
                             (500, b'bad gateway'), (200, b'[]'),
                             (200, b'{"ok":true}'), (200, b'x' * 65537)):
            self.response.status, self.response.read.return_value = status, body
            with self.assertRaises(NotificationDeliveryError) as caught:
                self.service._send("test")
            self.assertNotIn("test-secret", str(caught.exception))

    def test_network_timeout_is_sanitized(self):
        self.connection.getresponse.side_effect = TimeoutError("123:test-secret")
        with self.assertRaises(NotificationDeliveryError) as caught:
            self.service._send("test")
        self.assertNotIn("test-secret", str(caught.exception))
        self.connection.close.assert_called_once()


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class TelegramPostgresTests(unittest.TestCase):
    setUpClass = classmethod(payment_tests.PaymentServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(payment_tests.PaymentServicePostgresTests.tearDownClass.__func__)
    tearDown = payment_tests.PaymentServicePostgresTests.tearDown
    payload = payment_tests.PaymentServicePostgresTests.payload
    payment = payment_tests.PaymentServicePostgresTests.payment

    def setUp(self):
        payment_tests.PaymentServicePostgresTests.setUp(self)
        self.app.config.update(TELEGRAM_BOT_TOKEN="123:test-secret", TELEGRAM_CHAT_ID="-100123")
        self.service = PaymentService()
        self.service.initialize(self.payment_id)
        self.transaction = self.payment().transaction_id
        db.session.rollback()
        self.gateway.status = "APPROVED"

    def expire_lease(self):
        self.payment().gateway_lease_until = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()

    def assert_paid(self):
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(db.session.get(Order, self.ids["order_id"]).payment_status, "PAID")
        self.assertEqual(db.session.get(Invoice, self.ids["invoice_id"]).payment_status, "PAID")
        db.session.rollback()

    def test_verified_callback_once_and_ack_survives_new_session(self):
        def send(text):
            self.assertFalse(db.session().in_transaction())
            # An independent connection observes PAID before the send.
            with db.engine.connect() as connection:
                self.assertEqual(connection.execute(db.select(Payment.payment_status).where(
                    Payment.id == self.payment_id)).scalar_one(), "PAID")
            self.assertIn("Customer: Dara", text)
            self.assertIn("Shoe x 2", text)
            self.assertIn("Total: 21.50 USD", text)
            self.assertIn(f"Event: payment:{self.payment_id}:paid", text)
            return 7
        with patch.object(TelegramNotificationService, "_send", side_effect=send) as sender:
            self.service.callback_hint(self.transaction)
            self.service.callback_hint(self.transaction)
            db.session.remove()
            PaymentService().verify(self.payment_id)
            self.assertEqual(TelegramNotificationService().retry_pending(), 0)
            sender.assert_called_once()
        self.assert_paid()
        self.assertEqual(self.payment().gateway_state, "PAID")

    def test_rate_limit_survives_restart_then_retries(self):
        with patch.object(TelegramNotificationService, "_send",
                          side_effect=NotificationDeliveryError("Rate limited", 3600)):
            self.service.verify(self.payment_id)
        self.assert_paid()
        payment = self.payment()
        self.assertEqual(payment.gateway_state, "PAID_NOTIFY_PENDING")
        self.assertGreater(payment.gateway_lease_until, DateUtil.now() + timedelta(minutes=59))
        db.session.remove()
        with patch.object(TelegramNotificationService, "_send", return_value=7) as sender:
            self.assertEqual(TelegramNotificationService().retry_pending(), 0)
            sender.assert_not_called()
            self.expire_lease()
            self.assertEqual(TelegramNotificationService().retry_pending(), 1)
            self.assertEqual(TelegramNotificationService().retry_pending(), 0)
            sender.assert_called_once()
        self.assert_paid()

    def test_missing_credentials_preserves_paid_and_pending_event(self):
        self.app.config["TELEGRAM_BOT_TOKEN"] = ""
        with patch("app.services.notifications.telegram_notification_service.http.client.HTTPSConnection") as http:
            self.service.verify(self.payment_id)
            http.assert_not_called()
        self.assert_paid()
        self.assertEqual(self.payment().gateway_state, "PAID_NOTIFY_PENDING")

    def test_message_is_bounded_with_safe_customer_content(self):
        order = db.session.get(Order, self.ids["order_id"])
        order.delivery_address = "<b>Address</b>\nPayment: FAKE " + "😀" * 5000
        original = db.session.scalar(db.select(OrderItem).where(OrderItem.order_id == order.id))
        for _ in range(40):
            db.session.add(OrderItem(order_id=order.id, product_id=original.product_id,
                variant_id=original.variant_id, variant_stock_id=original.variant_stock_id,
                product_code=original.product_code, product_name="😀" * 100,
                sku=original.sku, quantity=1, unit_price=original.unit_price, subtotal=original.subtotal))
        db.session.commit()
        with patch.object(TelegramNotificationService, "_send", return_value=7) as sender:
            self.service.verify(self.payment_id)
        text = sender.call_args.args[0]
        self.assertLessEqual(len(text.encode("utf-16-le")) // 2, 4096)
        self.assertIn("more order lines", text)
        self.assertNotIn("\nPayment: FAKE", text)

    def test_timeout_preserves_paid(self):
        with patch("app.services.notifications.telegram_notification_service.http.client.HTTPSConnection",
                   side_effect=TimeoutError("secret")):
            self.service.verify(self.payment_id)
        self.assert_paid()
        self.assertEqual(self.payment().gateway_state, "PAID_NOTIFY_PENDING")

    def test_ambiguous_delivery_can_repeat_same_event_on_retry(self):
        # Model Telegram accepting a message but its response being lost. This
        # documents the unavoidable window, rather than claiming exactly once.
        accepted = []
        def accept_then_timeout(text):
            accepted.append(text)
            raise NotificationDeliveryError("Uncertain outcome")
        with patch.object(TelegramNotificationService, "_send", side_effect=accept_then_timeout):
            self.service.verify(self.payment_id)
        self.expire_lease()
        with patch.object(TelegramNotificationService, "_send", side_effect=lambda text: accepted.append(text) or 7):
            TelegramNotificationService().retry_pending()
        self.assertEqual(len(accepted), 2)
        self.assertEqual(accepted[0], accepted[1])
        self.assert_paid()

    def test_nonpaid_and_unverified_events_do_not_send(self):
        with patch.object(TelegramNotificationService, "_send") as sender:
            for status in ("PENDING", "FAILED", "CANCELLED", "PAID"):
                self.payment().payment_status = status
                db.session.commit()
                event = {"event_id": f"payment:{self.payment_id}:paid", "payment_id": self.payment_id,
                         "order_id": self.ids["order_id"]}
                with self.assertRaises(NotificationDeliveryError):
                    TelegramNotificationService().notify_verified_payment(event)
            sender.assert_not_called()

    def test_cancelled_order_late_approval_does_not_send(self):
        self.gateway.status = "PENDING"
        self.service.cancel(self.payment_id, 1, "Changed mind")
        self.gateway.status = "APPROVED"
        with patch.object(TelegramNotificationService, "_send") as sender:
            self.service.verify(self.payment_id)
            sender.assert_not_called()
        self.assert_paid()
        self.assertEqual(self.payment().gateway_state, "REFUND_REVIEW_NOTIFY_PENDING")

    def test_concurrent_dispatch_one_send(self):
        with patch.object(TelegramNotificationService, "_send", side_effect=NotificationDeliveryError("deferred")):
            self.service.verify(self.payment_id)
        self.expire_lease()
        barrier = Barrier(2)
        def worker():
            with self.app.app_context():
                barrier.wait(timeout=10)
                return PaymentStateService(paid_hook=TelegramNotificationService().notify_verified_payment).dispatch_paid_notification(self.payment_id)
        with patch.object(TelegramNotificationService, "_send", return_value=7) as sender:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(pool.map(lambda _: worker(), range(2)))
            self.assertEqual(sorted(results), [False, True])
            sender.assert_called_once()
