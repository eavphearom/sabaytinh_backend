import json
import unittest
from contextlib import redirect_stderr
from io import StringIO
from unittest.mock import Mock, patch
from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import GatewayError
from tests import test_payway_client as fixture
from tests.test_payway_sandbox import run_sandbox_smoke


class PayWayDiagnosticTests(unittest.TestCase):
    setUp = fixture.PayWayClientTests.setUp
    qr = fixture.PayWayClientTests.qr
    approved = fixture.PayWayClientTests.approved

    def transport(self, status, response):
        connection = Mock()
        connection.getresponse.return_value.status = status
        connection.getresponse.return_value.read.return_value = json.dumps(response).encode()
        return patch("http.client.HTTPSConnection", return_value=connection)

    def test_http_error_records_only_allowlisted_fields(self):
        response = {"status": {"code": "403", "message": "private-secret", "hash": "private-secret"},
                    "qrString": "private-secret", "email": "private-secret", "data": {"apv": "private-secret"}}
        with self.transport(403, response), self.assertLogs("app.services.payments.payway_client", level="WARNING") as logs:
            with self.assertRaises(GatewayError): self.client.verify(self.context)
        text = " ".join(logs.output)
        self.assertIn("operation=verify", text)
        self.assertIn("http_status=403", text)
        self.assertIn("gateway_code=403", text)
        self.assertNotIn("private-secret", text)
        self.assertNotIn("unit-test-key", text)

    def test_non_protocol_error_code_and_raw_html_not_logged(self):
        with self.transport(200, {"status": {"code": "private-secret"}}), self.assertLogs("app.services.payments.payway_client") as logs:
            with self.assertRaises(GatewayError): self.client.verify(self.context)
        self.assertNotIn("private-secret", " ".join(logs.output))
        self.assertIn("gateway_status_rejected", " ".join(logs.output))
        connection = Mock()
        connection.getresponse.return_value.status = 502
        connection.getresponse.return_value.read.return_value = b"<html>private-secret</html>"
        with patch("http.client.HTTPSConnection", return_value=connection), self.assertLogs("app.services.payments.payway_client") as logs:
            with self.assertRaises(GatewayError): self.client.verify(self.context)
        self.assertIn("http_status=502", " ".join(logs.output))
        self.assertNotIn("private-secret", " ".join(logs.output))

    def test_qr_success_check_validation_failure_never_calls_close(self):
        approved = self.approved()
        approved["data"]["original_amount"] = None
        output = StringIO()
        with patch.object(self.client, "_post", side_effect=[self.qr(), approved]) as post, redirect_stderr(output), self.assertLogs("app.services.payments.payway_client") as logs:
            with self.assertRaisesRegex(AssertionError, "Cleanup requires manual follow-up.*UNRESOLVED_VERIFICATION"):
                run_sandbox_smoke(self.client, self.context)
        self.assertEqual(post.call_count, 2)
        self.assertIn("READY_CONFIRMED", output.getvalue())
        self.assertIn("amount_mismatch", " ".join(logs.output))

    def test_supported_check_response_and_security_still_enforced(self):
        for field, value, reason in (("payment_currency", "KHR", "currency_mismatch"),
                                     ("payment_status_code", "0", "contradictory_payment_status")):
            response = self.approved(); response["data"][field] = value
            with patch.object(self.client, "_post", return_value=response), self.assertLogs("app.services.payments.payway_client") as logs:
                with self.assertRaises(GatewayError): self.client.verify(self.context)
            self.assertIn(reason, " ".join(logs.output))
        response = self.approved(); response["status"]["tran_id"] = "wrong"
        with patch.object(self.client, "_post", return_value=response):
            with self.assertRaises(GatewayError): self.client.verify(self.context)
        with patch.object(self.client, "_post", return_value=self.approved()):
            self.assertEqual(self.client.verify(self.context).status, "APPROVED")

    def test_timeout_logs_no_exception_contents(self):
        connection = Mock(); connection.connect.side_effect = TimeoutError("private-secret")
        with patch("http.client.HTTPSConnection", return_value=connection), self.assertLogs("app.services.payments.payway_client") as logs:
            with self.assertRaises(GatewayError): self.client.verify(self.context)
        self.assertIn("transport_or_json_failure", " ".join(logs.output))
        self.assertNotIn("private-secret", " ".join(logs.output))

    def test_worker_budget_is_not_reported_as_gateway_validation_failure(self):
        from app.workers.execution_scope import ExecutionScope, execution_scope, WorkerStopped
        with execution_scope(ExecutionScope(1)), patch("http.client.HTTPSConnection") as http, \
             self.assertLogs("app.services.payments.payway_client") as logs:
            with self.assertRaises(WorkerStopped):
                self.client.verify(self.context)
            http.assert_not_called()
        text = " ".join(logs.output)
        self.assertIn("worker_abort=insufficient_io_budget", text)
        self.assertIn("gateway_admission", text)
        self.assertNotIn("validation_failure", text)
        self.assertNotIn("unit-test-key", text)


    def test_currency_formats_are_visible_without_currency_values(self):
        from app.services.payments.payway_client import currency_diagnostic
        from app.payway_verify_only import DiagnosticCapture
        import logging
        capture = DiagnosticCapture()
        logger = logging.getLogger("app.services.payments.payway_client")
        logger.addHandler(capture)
        try:
            for value, kind in ((None, "null"), ("", "empty"), (123, "non_string"),
                                ("usd", "invalid_format"), ("KHR", "supported_code"),
                                ("private-secret", "invalid_format")):
                currency_diagnostic({"payment_currency": value, "original_currency": "USD"}, "USD")
                result = capture.result["currency_fields"]
                self.assertEqual(result["payment_currency"]["format"], kind)
                self.assertFalse(result["payment_currency"]["matches_expected"])
                self.assertTrue(result["original_currency"]["matches_expected"])
                self.assertNotIn("private-secret", json.dumps(result))
            currency_diagnostic({}, "USD")
            self.assertEqual(capture.result["currency_fields"]["original_currency"]["format"], "missing")
        finally:
            logger.removeHandler(capture)

    def test_documented_check_format_passes_and_other_endpoint_formats_fail_closed(self):
        # Check Transaction's published success example has no original_currency.
        with patch.object(self.client, "_post", return_value=self.approved()):
            self.assertEqual(self.client.verify(self.context).status, "APPROVED")
        # Other ABA endpoints document these shapes; not proof they are valid
        # Check responses. Keep them unresolved until that contract is confirmed.
        for status, code, payer_currency in (("APPROVED", 0, "KHR"),):
            response = self.approved()
            response["data"].update(original_currency="USD", payment_currency=payer_currency,
                payment_status=status, payment_status_code=code)
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError): self.client.verify(self.context)
