import json
import unittest
from unittest.mock import patch
from app.payway_close_only import CloseOnlyClient, run_close
from tests import test_payway_client as fixture


class CloseOnlyTests(unittest.TestCase):
    setUp = fixture.PayWayClientTests.setUp
    approved = fixture.PayWayClientTests.approved

    def response(self, status):
        result = self.approved()
        result["data"].update(payment_status=status, payment_status_code={"PENDING": 2, "APPROVED": 0, "CANCELLED": 7}[status])
        if status != "APPROVED":
            result["data"]["apv"] = ""
        return result

    def run_close(self, **changes):
        args = dict(config=self.client.config, transaction_id=self.context.transaction_id,
            merchant_id=self.context.merchant_id, amount="10.00", currency="USD", allow_live_close=True)
        args.update(changes)
        return run_close(**args)

    def close_response(self):
        return {"status": {"code": "00", "tran_id": self.context.transaction_id}}

    def test_opt_in_and_context_before_http(self):
        with patch("http.client.HTTPSConnection") as http:
            for changes in ({"allow_live_close": False}, {"merchant_id": "wrong"}, {"amount": "0"}):
                self.assertEqual(self.run_close(**changes)[1], 2)
            http.assert_not_called()

    def test_check_close_check_order_and_confirmed_status(self):
        with patch.object(CloseOnlyClient, "_post", side_effect=[self.response("PENDING"), self.close_response(), self.response("CANCELLED")]) as post:
            result, code = self.run_close()
        self.assertEqual([c.args[0] for c in post.call_args_list], [CloseOnlyClient.CHECK_PATH, CloseOnlyClient.CLOSE_PATH, CloseOnlyClient.CHECK_PATH])
        self.assertEqual(code, 0)
        self.assertTrue(result["close_api_confirmed"])
        self.assertTrue(result["final_cancelled_confirmed"])

    def test_approved_or_invalid_check_never_closes(self):
        for response in (self.approved(), {"status": {"code": "error"}}):
            with patch.object(CloseOnlyClient, "_post", return_value=response) as post:
                result, code = self.run_close()
            self.assertEqual(code, 1)
            self.assertEqual(post.call_count, 1)
            self.assertFalse(result["close_api_confirmed"])

    def test_close_success_is_not_final_status(self):
        for final in (self.response("PENDING"), TimeoutError("private-secret")):
            with patch.object(CloseOnlyClient, "_post", side_effect=[self.response("PENDING"), self.close_response(), final]):
                result, code = self.run_close()
            self.assertTrue(result["close_api_confirmed"])
            self.assertFalse(result["final_cancelled_confirmed"])
            self.assertEqual(result["outcome"], "CLOSE_ACCEPTED_FINAL_STATUS_UNCONFIRMED")
            self.assertEqual(code, 1)
            self.assertNotIn("private-secret", json.dumps(result))

    def test_close_timeout_or_mismatch_never_confirms_closure(self):
        for failed in (TimeoutError("private-secret"), {"status": {"code": "00", "tran_id": "wrong"}}):
            with patch.object(CloseOnlyClient, "_post", side_effect=[self.response("PENDING"), failed, self.response("CANCELLED")]) as post:
                result, code = self.run_close()
            self.assertEqual(code, 1)
            self.assertFalse(result["close_api_confirmed"])
            self.assertFalse(result["final_cancelled_confirmed"])
            self.assertEqual(post.call_count, 3)

    def test_payment_race_requires_review(self):
        with patch.object(CloseOnlyClient, "_post", side_effect=[self.response("PENDING"), self.close_response(), self.approved()]):
            result, code = self.run_close()
        self.assertEqual(result["outcome"], "PAID_MANUAL_REVIEW")
        self.assertEqual(code, 1)

    def test_no_qr_and_no_configuration_mutation(self):
        config = dict(self.client.config, PAYWAY_SANDBOX_ENABLED=False, PAYWAY_PUBLIC_API_ENABLED=False)
        before = dict(config)
        with patch.object(CloseOnlyClient, "_post", return_value=self.approved()):
            self.run_close(config=config, enable_sandbox_for_close=True)
        self.assertEqual(config, before)
        client = CloseOnlyClient(config)
        with patch("http.client.HTTPSConnection") as http:
            with self.assertRaises(RuntimeError): client.initialize(self.context)
            with self.assertRaises(RuntimeError): client._post(client.QR_PATH, {})
            http.assert_not_called()
