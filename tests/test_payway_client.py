import base64
from decimal import Decimal
import hashlib
import hmac
from unittest import TestCase
from unittest.mock import patch

from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import PaymentContext, GatewayError


class PayWayClientTests(TestCase):
    def setUp(self):
        self.client = PayWayClient({
            "PAYWAY_SANDBOX_ENABLED": True,
            "PAYWAY_BASE_URL": "https://checkout-sandbox.payway.com.kh",
            "PAYWAY_MERCHANT_ID": "test_merchant", "PAYWAY_API_KEY": "unit-test-key",
            "PAYWAY_CALLBACK_URL": "https://example.test/callback",
        })
        self.context = PaymentContext(1, 1, "testtransaction", "test_merchant", Decimal("10.00"), "USD", "lease")

    def qr(self):
        return {"status": {"code": "0"}, "amount": Decimal("10.00"), "currency": "USD",
                "qrString": "mock-qr", "qrImage": "data:image/png;base64,dGVzdA==",
                "abapay_deeplink": "abamobilebank://mock"}

    def approved(self):
        return {"status": {"code": "00", "tran_id": "testtransaction"},
                "data": {"payment_status_code": 0, "payment_status": "APPROVED",
                         "original_amount": Decimal("10"), "total_amount": Decimal("10"),
                         "payment_amount": Decimal("10"), "refund_amount": 0,
                         "payment_currency": "USD", "apv": "test-approval"}}

    def test_qr_initialization_and_exact_signing_order(self):
        with patch.object(self.client, "_post", return_value=self.qr()) as post:
            result = self.client.initialize(self.context)
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.qr_string, "mock-qr")
        self.assertIsNotNone(result.expires_at)
        path, payload = post.call_args.args
        self.assertEqual(path, PayWayClient.QR_PATH)
        self.assertEqual(payload["amount"], Decimal("10.00"))
        # Independent explicit construction of the documented concatenation.
        message = (payload["req_time"] + "test_merchant" + "testtransaction" + "10.00"
                   + "purchase" + "abapay_khqr" + payload["callback_url"] + "USD"
                   + "15" + "template3_color")
        expected = base64.b64encode(hmac.new(b"unit-test-key", message.encode(), hashlib.sha512).digest()).decode()
        self.assertEqual(payload["hash"], expected)
        self.assertNotIn("api_key", payload)

    def test_invalid_hash_and_malformed_qr_rejected(self):
        for response in ({"status": {"code": "1"}}, {}, {**self.qr(), "currency": "KHR"},
                         {**self.qr(), "amount": "9.99"}, {**self.qr(), "qrString": None}):
            with self.subTest(response=response), patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError):
                    self.client.initialize(self.context)

    def test_all_qr_fields_match_spring_order_and_transaction_signing(self):
        fields = ("req_time", "merchant_id", "tran_id", "amount", "items", "first_name",
                  "last_name", "email", "phone", "purchase_type", "payment_option",
                  "callback_url", "return_deeplink", "currency", "custom_fields",
                  "return_params", "payout", "lifetime", "qr_image_template")
        self.assertEqual(PayWayClient.QR_SIGN_FIELDS, fields)
        payload = {key: str(index) + ":" for index, key in enumerate(fields)}
        expected = base64.b64encode(hmac.new(b"unit-test-key",
            "".join(str(index) + ":" for index in range(19)).encode(), hashlib.sha512).digest()).decode()
        self.assertEqual(self.client._sign(payload, PayWayClient.QR_SIGN_FIELDS), expected)
        for method, response in ((self.client.verify, self.approved()),
                                 (self.client.close, {"status": {"code": "00", "tran_id": "testtransaction"}})):
            with patch.object(self.client, "_post", return_value=response) as post:
                method(self.context)
            sent = post.call_args.args[1]
            message = sent["req_time"] + "test_merchant" + "testtransaction"
            expected = base64.b64encode(hmac.new(b"unit-test-key", message.encode(), hashlib.sha512).digest()).decode()
            self.assertEqual(sent["hash"], expected)

    def test_verified_approval_and_mismatches(self):
        with patch.object(self.client, "_post", return_value=self.approved()):
            self.assertEqual(self.client.verify(self.context).status, "APPROVED")
        for key, value in (("payment_amount", "9.99"), ("original_amount", "9.99"),
                           ("payment_currency", "KHR"), ("payment_status", "PRE-AUTH"),
                           ("payment_status_code", True), ("refund_amount", "1"), ("apv", None)):
            response = self.approved()
            response["data"][key] = value
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError):
                    self.client.verify(self.context)
        response = self.approved()
        response["status"]["tran_id"] = "another-transaction"
        with patch.object(self.client, "_post", return_value=response):
            with self.assertRaises(GatewayError):
                self.client.verify(self.context)

    def test_closure_requires_exact_transaction_confirmation(self):
        with patch.object(self.client, "_post", return_value={"status": {"code": "00", "tran_id": "testtransaction"}}):
            self.assertEqual(self.client.close(self.context).status, "CLOSED")
        for response in ({"status": {"code": "5"}}, {"status": {"code": "00", "tran_id": "other"}}):
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError):
                    self.client.close(self.context)

    def test_transport_timeouts_bad_json_and_http_errors(self):
        with patch("app.services.payments.payway_client.http.client.HTTPSConnection") as factory:
            connection = factory.return_value
            connection.connect.side_effect = TimeoutError("sensitive provider error")
            with self.assertRaises(GatewayError) as caught:
                self.client._post(PayWayClient.CHECK_PATH, {})
            self.assertNotIn("sensitive", str(caught.exception))
            connection.close.assert_called_once()
        for status, body in ((500, b'{}'), (302, b'{}'), (200, b'not json'), (200, b'[]')):
            with patch("app.services.payments.payway_client.http.client.HTTPSConnection") as factory:
                response = factory.return_value.getresponse.return_value
                response.status = status
                response.read.return_value = body
                with self.assertRaises(GatewayError):
                    self.client._post(PayWayClient.CHECK_PATH, {})

    def test_configuration_fails_closed(self):
        for key, value in (("PAYWAY_SANDBOX_ENABLED", False), ("PAYWAY_API_KEY", ""),
                           ("PAYWAY_BASE_URL", "https://checkout.payway.com.kh"),
                           ("PAYWAY_CALLBACK_URL", "http://example.test"),
                           ("PAYWAY_READ_TIMEOUT", 0), ("PAYWAY_LEASE_SECONDS", 1)):
            config = {**self.client.config, key: value}
            with self.subTest(key=key), self.assertRaises(GatewayError):
                PayWayClient(config).ensure_configured()
