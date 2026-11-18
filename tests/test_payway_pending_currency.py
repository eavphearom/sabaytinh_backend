import unittest
from unittest.mock import patch
from app.services.payments.payment_strategy import GatewayError
from app.payway_verify_only import run_check
from tests import test_payway_client as fixture


class PendingCurrencyTests(unittest.TestCase):
    setUp = fixture.PayWayClientTests.setUp
    approved = fixture.PayWayClientTests.approved

    def pending(self):
        response = self.approved()
        response["data"].update(payment_status="PENDING", payment_status_code=2,
            payment_currency="", payment_amount=0, apv="")
        return response

    def test_pending_empty_and_absent_currency(self):
        for absent in (False, True):
            response = self.pending()
            if absent: del response["data"]["payment_currency"]
            with patch.object(self.client, "_post", return_value=response):
                result = self.client.verify(self.context)
                self.assertEqual(result.status, "PENDING")
                self.assertIsNone(result.reference)
                self.assertEqual(result.currency, "USD")

    def test_amounts_still_required(self):
        for field in ("original_amount", "total_amount"):
            for value in (None, 999, True):
                response = self.pending(); response["data"][field] = value
                with patch.object(self.client, "_post", return_value=response):
                    with self.assertRaises(GatewayError): self.client.verify(self.context)

    def test_malformed_or_different_currency_rejected(self):
        for value in (None, 0, {}, " ", "usd", "KHR"):
            response = self.pending(); response["data"]["payment_currency"] = value
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError): self.client.verify(self.context)
        response = self.pending(); response["data"]["original_currency"] = "KHR"
        with patch.object(self.client, "_post", return_value=response):
            with self.assertRaises(GatewayError): self.client.verify(self.context)

    def test_contradictory_and_unsupported_status_pairs(self):
        for status, code in (("PENDING", 0), ("APPROVED", 2), ("PENDING", "2"),
                             ("PENDING", True), ("PAID", 0), ({}, 2), (None, 2)):
            response = self.pending(); response["data"].update(payment_status=status, payment_status_code=code)
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError): self.client.verify(self.context)

    def test_approved_requires_existing_evidence(self):
        with patch.object(self.client, "_post", return_value=self.approved()):
            self.assertEqual(self.client.verify(self.context).status, "APPROVED")
        for field, value in (("payment_currency", ""), ("payment_currency", "KHR"), ("apv", ""),
                             ("payment_amount", 999), ("refund_amount", 1)):
            response = self.approved(); response["data"][field] = value
            with patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError): self.client.verify(self.context)

    def test_pending_with_approval_or_refund_evidence_is_rejected(self):
        for field, value in (("apv", "approval-reference"), ("apv", 123),
                             ("refund_amount", 1), ("refund_amount", "invalid")):
            response = self.pending()
            response["data"][field] = value
            with self.subTest(field=field, value=value), patch.object(self.client, "_post", return_value=response):
                with self.assertRaises(GatewayError):
                    self.client.verify(self.context)

    def test_diagnostic_confirms_pair_without_sensitive_values(self):
        with patch("app.services.payments.payway_client.PayWayClient._post", return_value=self.pending()):
            result, code = run_check(self.client.config, self.context.transaction_id,
                self.context.merchant_id, "10.00", "USD", allow_live_check=True)
        self.assertEqual(code, 0)
        self.assertEqual(result["payment_status"], "PENDING")
        self.assertEqual(result["payment_status_code"], 2)
        self.assertIsNone(result["validation_failure_reason"])
