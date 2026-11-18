import json
import unittest
from unittest.mock import Mock, patch
from app.payway_verify_only import run_check, VerificationOnlyClient
from tests import test_payway_client as fixture


class VerificationOnlyTests(unittest.TestCase):
    setUp = fixture.PayWayClientTests.setUp
    approved = fixture.PayWayClientTests.approved

    def run_check(self, **changes):
        args = dict(config=self.client.config, transaction_id=self.context.transaction_id,
            merchant_id=self.context.merchant_id, amount="10.00", currency="USD", allow_live_check=True)
        args.update(changes)
        return run_check(**args)

    def test_requires_opt_in_and_exact_context_before_network(self):
        with patch("http.client.HTTPSConnection") as network:
            for changes in ({"allow_live_check": False}, {"merchant_id": "wrong"}, {"currency": "KHR"},
                            {"amount": "NaN"}, {"amount": "0"}, {"transaction_id": ""}):
                result, code = self.run_check(**changes)
                self.assertEqual(code, 2)
                self.assertIsNotNone(result["validation_failure_reason"])
            network.assert_not_called()

    def test_only_check_is_sent_and_output_contains_no_values(self):
        response = self.approved()
        response["status"]["message"] = "private-secret"
        response["data"]["qrString"] = "private-secret"
        connection = Mock()
        connection.getresponse.return_value.status = 200
        # Convert Decimal fixture values without leaking them into output.
        connection.getresponse.return_value.read.return_value = json.dumps(response, default=str).encode()
        original = dict(self.client.config)
        with patch("http.client.HTTPSConnection", return_value=connection):
            result, code = self.run_check()
        self.assertEqual(code, 0)
        connection.request.assert_called_once()
        self.assertEqual(connection.request.call_args.args[:2], ("POST", VerificationOnlyClient.CHECK_PATH))
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["gateway_status_code"], "00")
        self.assertIsNone(result["validation_failure_reason"])
        for secret in ("private-secret", "test-approval", "testtransaction", "unit-test-key", "test_merchant"):
            self.assertNotIn(secret, json.dumps(result))
        self.assertEqual(self.client.config, original)

    def test_timeout_has_no_retry_or_raw_exception(self):
        connection = Mock(); connection.connect.side_effect = TimeoutError("private-secret")
        with patch("http.client.HTTPSConnection", return_value=connection) as network:
            result, code = self.run_check()
        self.assertEqual(code, 1)
        network.assert_called_once()
        self.assertEqual(result["validation_failure_reason"], "transport_or_json_failure")
        self.assertNotIn("private-secret", json.dumps(result))

    def test_write_operations_are_prohibited(self):
        client = VerificationOnlyClient(self.client.config, require_callback=False)
        with patch("http.client.HTTPSConnection") as network:
            for operation in (client.initialize, client.close):
                with self.assertRaises(RuntimeError): operation(self.context)
            with self.assertRaises(RuntimeError): client._post(client.QR_PATH, {})
            with self.assertRaises(RuntimeError): client._post(client.CLOSE_PATH, {})
            network.assert_not_called()

    def test_missing_fields_fail_without_closure(self):
        connection = Mock()
        connection.getresponse.return_value.status = 200
        connection.getresponse.return_value.read.return_value = json.dumps({
            "status": {"code": "00", "tran_id": self.context.transaction_id}, "data": {"payment_status": "PENDING", "payment_status_code": 2}}).encode()
        with patch("http.client.HTTPSConnection", return_value=connection):
            result, code = self.run_check()
        self.assertEqual(code, 1)
        self.assertEqual(result["validation_failure_reason"], "amount_mismatch")
        self.assertEqual(result["response_field_types"]["original_amount"], "missing")
        connection.request.assert_called_once()


    def test_specific_configuration_failures_without_network(self):
        cases = [({"PAYWAY_SANDBOX_ENABLED": False}, "sandbox_disabled"),
            ({"PAYWAY_BASE_URL": "https://example.test"}, "invalid_sandbox_host"),
            ({"PAYWAY_API_KEY": ""}, "api_key_missing"),
            ({"PAYWAY_MERCHANT_ID": ""}, "invalid_merchant_configuration"),
            ({"PAYWAY_CONNECT_TIMEOUT": 0}, "invalid_gateway_timeouts"),
            ({"PAYWAY_LEASE_SECONDS": 1}, "invalid_gateway_lease"),
            ({"PAYWAY_QR_LIFETIME_MINUTES": 1}, "invalid_qr_lifetime")]
        with patch("http.client.HTTPSConnection") as network:
            for changes, reason in cases:
                result, code = self.run_check(config={**self.client.config, **changes})
                self.assertEqual(code, 2)
                self.assertEqual(result["validation_failure_reason"], reason)
            network.assert_not_called()

    def test_process_local_enablement_and_preflight_do_not_mutate_flags(self):
        config = {**self.client.config, "PAYWAY_SANDBOX_ENABLED": False,
            "PAYWAY_PUBLIC_API_ENABLED": False, "PAYWAY_SANDBOX_VERIFIED": False,
            "PAYWAY_CALLBACK_APPROVED": False, "PAYWAY_WORKER_VERIFIED": False}
        before = dict(config)
        with patch("http.client.HTTPSConnection") as network:
            result, code = self.run_check(config=config, enable_sandbox_for_check=True,
                check_config=True, allow_live_check=False)
            self.assertEqual(code, 0)
            self.assertIsNone(result["validation_failure_reason"])
            self.assertEqual(config, before)
            result, code = self.run_check(config=config, enable_sandbox_for_check=True, allow_live_check=False)
            self.assertEqual(code, 2)
            network.assert_not_called()

    def test_numeric_loader_error_is_sanitized(self):
        import os
        from io import StringIO
        from contextlib import redirect_stdout
        from app.payway_verify_only import main
        output = StringIO()
        with patch.dict(os.environ, {"PAYWAY_CONNECT_TIMEOUT": "private-secret"}), redirect_stdout(output), patch("http.client.HTTPSConnection") as network:
            code = main(["--transaction-id", "original", "--merchant-id", "original", "--amount", "0.01", "--currency", "USD", "--check-config"])
            network.assert_not_called()
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(output.getvalue())["validation_failure_reason"], "invalid_config_number_payway_connect_timeout")
        self.assertNotIn("private-secret", output.getvalue())
