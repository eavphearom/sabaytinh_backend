"""Offline protocol tests: the network boundary is always mocked."""
import base64
from contextlib import redirect_stderr
from io import StringIO
import hashlib
import hmac
import unittest
from unittest.mock import patch

from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import GatewayError
from tests.test_payway_sandbox_qr_only import run_qr_only_probe


class QROnlyTests(unittest.TestCase):
    def config(self):
        return {"PAYWAY_SANDBOX_ENABLED": True,
                "PAYWAY_BASE_URL": "https://checkout-sandbox.payway.com.kh",
                "PAYWAY_MERCHANT_ID": "test-merchant", "PAYWAY_API_KEY": "test-key",
                "PAYWAY_CALLBACK_URL": "", "PAYWAY_CALLBACK_SECRET": "",
                "PAYWAY_PUBLIC_API_ENABLED": False, "PAYWAY_CALLBACK_APPROVED": False,
                "PAYWAY_SANDBOX_VERIFIED": False, "PAYWAY_WORKER_VERIFIED": False}

    def test_default_client_still_requires_callback(self):
        with self.assertRaises(GatewayError):
            PayWayClient(self.config()).ensure_configured()

    def test_internal_mode_still_rejects_disabled_sandbox_and_production(self):
        for changes in ({"PAYWAY_SANDBOX_ENABLED": False},
                        {"PAYWAY_BASE_URL": "https://checkout.payway.com.kh"},
                        {"PAYWAY_API_KEY": ""}, {"PAYWAY_CALLBACK_URL": "not-a-url"}):
            with self.assertRaises(GatewayError):
                PayWayClient({**self.config(), **changes}, require_callback=False).ensure_configured()

    def test_probe_omits_callback_signs_correctly_and_closes_same_id(self):
        config = self.config()
        original = dict(config)
        requests = []
        def post(path, payload):
            requests.append((path, payload))
            self.assertNotIn("callback_url", payload)
            if path == PayWayClient.QR_PATH:
                message = (payload["req_time"] + "test-merchant" + payload["tran_id"] + "0.01"
                           + "purchaseabapay_khqrUSD15template3_color")
                self.assertEqual(payload["hash"], base64.b64encode(hmac.new(
                    b"test-key", message.encode(), hashlib.sha512).digest()).decode())
                return {"status": {"code": "0"}, "amount": "0.01", "currency": "USD",
                        "qrString": "test-qr", "qrImage": "data:image/png;base64,dGVzdA==",
                        "abapay_deeplink": "abamobilebank://test"}
            status = {"code": "00", "tran_id": payload["tran_id"]}
            if path == PayWayClient.CHECK_PATH:
                return {"status": status, "data": {"original_amount": "0.01", "total_amount": "0.01",
                    "payment_currency": "USD", "payment_status": "PENDING", "payment_status_code": 2}}
            self.assertEqual(path, PayWayClient.CLOSE_PATH)
            return {"status": status}
        with patch.object(PayWayClient, "_post", side_effect=post), redirect_stderr(StringIO()):
            run_qr_only_probe(config)
        self.assertEqual([path for path, _ in requests], [PayWayClient.QR_PATH, PayWayClient.CHECK_PATH, PayWayClient.CLOSE_PATH])
        self.assertEqual(len({payload["tran_id"] for _, payload in requests}), 1)
        self.assertEqual(config, original)

    def test_qr_timeout_recovers_same_transaction_in_callback_free_mode(self):
        requests = []
        output = StringIO()
        def post(path, payload):
            requests.append((path, payload["tran_id"]))
            self.assertNotIn("callback_url", payload)
            if path == PayWayClient.QR_PATH:
                raise TimeoutError("test-only-private-error")
            status = {"code": "00", "tran_id": payload["tran_id"]}
            if path == PayWayClient.CHECK_PATH:
                return {"status": status, "data": {"original_amount": "0.01", "total_amount": "0.01",
                    "payment_currency": "USD", "payment_status": "PENDING", "payment_status_code": 2}}
            return {"status": status}
        with patch.object(PayWayClient, "_post", side_effect=post), redirect_stderr(output), \
                self.assertRaisesRegex(AssertionError, "initialization failed.*CLOSED_CONFIRMED"):
            run_qr_only_probe(self.config())
        self.assertEqual([path for path, _ in requests], [PayWayClient.QR_PATH, PayWayClient.CHECK_PATH, PayWayClient.CLOSE_PATH])
        self.assertEqual(len({id for _, id in requests}), 1)
        self.assertNotIn("test-only-private-error", output.getvalue())

    def test_qr_timeout_and_check_failure_report_unresolved_id(self):
        requests = []
        output = StringIO()
        def post(path, payload):
            requests.append((path, payload["tran_id"]))
            raise TimeoutError("test-only-private-error")
        with patch.object(PayWayClient, "_post", side_effect=post), redirect_stderr(output), \
                self.assertRaisesRegex(AssertionError, "UNRESOLVED_VERIFICATION"):
            run_qr_only_probe(self.config())
        self.assertEqual([path for path, _ in requests], [PayWayClient.QR_PATH, PayWayClient.CHECK_PATH])
        self.assertEqual(requests[0][1], requests[1][1])
        self.assertIn(requests[0][1], output.getvalue())
        self.assertNotIn("test-only-private-error", output.getvalue())
