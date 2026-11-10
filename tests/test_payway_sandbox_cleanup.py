"""Offline-only smoke-test recovery tests; every client operation is mocked."""
from contextlib import redirect_stderr
from dataclasses import replace
from decimal import Decimal
from io import StringIO
import unittest
from unittest.mock import Mock, call

from app.services.payments.payment_strategy import PaymentContext, GatewayResult
from tests.test_payway_sandbox import run_sandbox_smoke


class SandboxCleanupTests(unittest.TestCase):
    def setUp(self):
        self.context = PaymentContext(0, 0, "offline-test-id", "test-merchant", Decimal("0.01"), "USD", "test")
        self.client = Mock(spec=["ensure_configured", "initialize", "verify", "close"])
        self.client.initialize.return_value = self.result("READY")
        self.client.verify.return_value = self.result("PENDING")
        self.client.close.return_value = self.result("CLOSED")
        self.output = StringIO()

    def result(self, status):
        return GatewayResult(self.context.transaction_id, self.context.merchant_id,
                             self.context.amount, self.context.currency, status)

    def run_failed(self, expected):
        with redirect_stderr(self.output), self.assertRaisesRegex(AssertionError, expected) as caught:
            run_sandbox_smoke(self.client, self.context)
        self.assertIn(self.context.transaction_id, str(caught.exception))
        self.assertNotIn("private-secret", str(caught.exception) + self.output.getvalue())

    def test_success_checks_then_confirms_closure(self):
        with redirect_stderr(self.output):
            run_sandbox_smoke(self.client, self.context)
        self.assertEqual(self.client.method_calls, [call.ensure_configured(), call.initialize(self.context),
            call.verify(self.context), call.close(self.context)])
        self.assertIn("CLOSED_CONFIRMED", self.output.getvalue())

    def test_initialization_timeout_still_checks_and_closes_same_transaction(self):
        def timeout(context):
            self.assertIn("MAY_EXIST", self.output.getvalue())
            raise TimeoutError("private-secret")
        self.client.initialize.side_effect = timeout
        self.run_failed("initialization failed.*CLOSED_CONFIRMED")
        self.client.initialize.assert_called_once_with(self.context)
        self.client.verify.assert_called_once_with(self.context)
        self.client.close.assert_called_once_with(self.context)

    def test_initialization_timeout_and_failed_check_remain_unresolved(self):
        self.client.initialize.side_effect = TimeoutError("private-secret")
        self.client.verify.side_effect = RuntimeError("private-secret")
        self.run_failed("UNRESOLVED_VERIFICATION")
        self.client.close.assert_not_called()

    def test_close_timeout_rechecks_without_claiming_closure(self):
        self.client.close.side_effect = TimeoutError("private-secret")
        self.client.verify.side_effect = [self.result("PENDING"), self.result("CANCELLED")]
        self.run_failed("UNRESOLVED_CLOSURE")
        self.assertEqual(self.client.verify.call_count, 2)
        self.client.close.assert_called_once_with(self.context)

    def test_close_and_followup_check_failure_report_transaction_id(self):
        self.client.close.side_effect = RuntimeError("private-secret")
        self.client.verify.side_effect = [self.result("PENDING"), TimeoutError("private-secret")]
        self.run_failed("UNRESOLVED_CLOSURE")
        self.assertIn("UNRESOLVED_CLOSURE", self.output.getvalue())

    def test_paid_transaction_is_not_closed(self):
        self.client.initialize.side_effect = TimeoutError("private-secret")
        self.client.verify.return_value = self.result("APPROVED")
        self.run_failed("PAID_MANUAL_REVIEW")
        self.client.close.assert_not_called()

    def test_payment_racing_closure_is_reported(self):
        self.client.close.side_effect = RuntimeError("private-secret")
        self.client.verify.side_effect = [self.result("PENDING"), self.result("APPROVED")]
        self.run_failed("PAID_MANUAL_REVIEW")

    def test_mismatched_close_evidence_is_not_confirmation(self):
        self.client.close.return_value = replace(self.result("CLOSED"), transaction_id="other")
        self.run_failed("UNRESOLVED_CLOSURE")

    def test_invalid_qr_response_also_cleans_up(self):
        self.client.initialize.return_value = self.result("INVALID")
        self.run_failed("initialization failed.*CLOSED_CONFIRMED")
        self.client.close.assert_called_once()

    def test_nonpending_status_is_cleaned_up_but_does_not_pass_smoke_test(self):
        self.client.verify.return_value = self.result("DECLINED")
        self.run_failed("CLOSED_CONFIRMED_UNEXPECTED_STATUS")
        self.client.close.assert_called_once()

    def test_configuration_failure_makes_no_requests(self):
        self.client.ensure_configured.side_effect = ValueError("Missing test configuration")
        with redirect_stderr(self.output), self.assertRaises(ValueError):
            run_sandbox_smoke(self.client, self.context)
        self.client.initialize.assert_not_called()
        self.client.verify.assert_not_called()
        self.client.close.assert_not_called()
        self.assertEqual(self.output.getvalue(), "")
