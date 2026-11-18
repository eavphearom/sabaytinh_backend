import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch

from flask import Flask
from app import payway_internal_test as probe


class InternalSandboxTests(unittest.TestCase):
    def test_authorization_required_before_app_or_services(self):
        with patch("app.create_app") as factory:
            self.assertEqual(probe.main(["create"]), 2)
            factory.assert_not_called()

    def test_configuration_keeps_readiness_and_rejects_public_enablement(self):
        app = Flask(__name__)
        app.config["PAYWAY_PUBLIC_API_ENABLED"] = False
        with patch.object(probe.PayWayClient, "ensure_configured") as validate:
            probe.prepare_config(app)
            validate.assert_called_once()
        self.assertFalse(app.config["PAYWAY_PUBLIC_API_ENABLED"])
        self.assertTrue(app.config["PAYWAY_SANDBOX_ENABLED"])
        app.config["PAYWAY_PUBLIC_API_ENABLED"] = True
        with self.assertRaises(ValueError):
            probe.prepare_config(app)

    def test_receipt_before_gateway_and_no_second_order(self):
        with TemporaryDirectory() as directory, patch.object(probe, "CheckoutService") as checkout, \
                patch.object(probe, "PaymentService") as payments:
            path = Path(directory) / "receipt.jsonl"
            checkout.return_value.checkout.return_value = {"order_id": 1, "payment_id": 2}
            def initialize(payment_id):
                self.assertEqual(payment_id, 2)
                self.assertIn('ORDER_COMMITTED', path.read_text())
                return {"qr_image": "data:image/png;base64,dGVzdA=="}
            payments.return_value.initialize.side_effect = initialize
            result, code = probe.create_probe(3, {"items": []}, path)
            self.assertEqual(code, 0)
            self.assertTrue(Path(result["qr_file"]).exists())
            self.assertNotIn("base64", path.read_text())
            with self.assertRaises(FileExistsError):
                probe.create_probe(3, {}, path)
            checkout.return_value.checkout.assert_called_once()

    def test_timeout_preserves_ids_without_cancel_or_retry(self):
        with TemporaryDirectory() as directory, patch.object(probe, "CheckoutService") as checkout, \
                patch.object(probe, "PaymentService") as payments:
            path = Path(directory) / "receipt.jsonl"
            checkout.return_value.checkout.return_value = {"order_id": 1, "payment_id": 2}
            payments.return_value.initialize.side_effect = TimeoutError("private")
            result, code = probe.create_probe(3, {}, path)
            self.assertEqual(code, 1)
            self.assertEqual(result["payment_id"], 2)
            self.assertEqual(json.loads(path.read_text().splitlines()[-1])["stage"], "INITIALIZATION_UNRESOLVED")
            self.assertNotIn("private", path.read_text())
            payments.return_value.cancel.assert_not_called()
            payments.return_value.initialize.assert_called_once()

    def test_checkout_failure_does_not_initialize(self):
        with TemporaryDirectory() as directory, patch.object(probe, "CheckoutService") as checkout, \
                patch.object(probe, "PaymentService") as payments:
            checkout.return_value.checkout.side_effect = ValueError()
            with self.assertRaises(ValueError):
                probe.create_probe(3, {}, Path(directory) / "receipt.jsonl")
            payments.assert_not_called()
