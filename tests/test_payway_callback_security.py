import base64
import hashlib
import hmac
import json
import unittest
from unittest.mock import patch

from flask import Flask

from app.extensions import db
from app.exceptions.handlers import register_error_handlers
from app.routes.v1.payway_callback_routes import register_payway_callback
from app.services.payments.payway_callback_security import verify_callback


SECRET = "callback-unit-test-secret"


def signature(message):
    return base64.b64encode(hmac.new(SECRET.encode(), message.encode(), hashlib.sha512).digest()).decode()


class CallbackSecurityTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True,
            PAYWAY_CALLBACK_URL="https://example.test/callback", PAYWAY_CALLBACK_SECRET=SECRET,
            PAYWAY_PUBLIC_API_ENABLED=True, PAYWAY_CALLBACK_APPROVED=True,
            PAYWAY_SANDBOX_VERIFIED=True, PAYWAY_WORKER_VERIFIED=True,
            PAYWAY_SANDBOX_ENABLED=True, PAYWAY_BASE_URL="https://checkout-sandbox.payway.com.kh",
            PAYWAY_MERCHANT_ID="test", PAYWAY_API_KEY="outbound-unit-test-key")
        db.init_app(self.app)
        register_error_handlers(self.app)
        register_payway_callback(self.app)
        self.client = self.app.test_client()
        self.hint_patch = patch("app.routes.v1.payway_callback_routes.PaymentService.callback_hint")
        self.hint = self.hint_patch.start()
        self.addCleanup(self.hint_patch.stop)

    def post(self, body, sig=None, content_type="application/json"):
        headers = {} if sig is None else {"X-PayWay-HMAC-SHA512": sig}
        return self.client.post("/callback", data=body, content_type=content_type, headers=headers)

    def test_valid_signature_uses_constant_time_comparison_before_hint(self):
        with patch("app.services.payments.payway_callback_security.hmac.compare_digest", wraps=hmac.compare_digest) as compare:
            response = self.post('{"tran_id":"abc","status":0}', signature("0abc"))
            self.assertEqual(response.status_code, 200)
            compare.assert_called_once()
            self.hint.assert_called_once_with("abc")

    def test_missing_malformed_and_wrong_signatures_fail_before_processing(self):
        for sig in (None, "", "x" * 88, " " + signature("abc"), signature("wrong"),
                    signature("abc") + "," + signature("abc"), "é" * 88):
            self.assertEqual(self.post('{"tran_id":"abc"}', sig).status_code, 401)
        self.hint.assert_not_called()

    def test_invalid_json_and_ambiguous_numbers_are_rejected(self):
        bodies = [b'{', b'[]', b'null', b'{"tran_id":"a","tran_id":"b"}',
                  b'{"x":NaN}', b'{"x":Infinity}', b'{"x":1e999999}',
                  b'{"x":1e999999999999999999999999}', b'{"x":"\xff"}',
                  b'{"x":"\\ud800"}', b'{"x":{"a":1,"a":2}}',
                  ('{"x":' + '[' * 40 + '0' + ']' * 40 + '}').encode()]
        for body in bodies:
            with self.subTest(body=body[:30]):
                self.assertEqual(self.post(body, signature("unused")).status_code, 400)
        self.hint.assert_not_called()

    def test_body_limit_content_type_and_missing_secret(self):
        self.assertEqual(self.post('x' * 16385, signature("unused")).status_code, 413)
        self.assertEqual(self.post('{}', signature(""), "text/plain").status_code, 400)
        self.app.config["PAYWAY_CALLBACK_SECRET"] = ""
        self.assertEqual(self.post('{"tran_id":"abc"}', signature("abc")).status_code, 503)
        self.hint.assert_not_called()

    def test_gate_remains_closed_even_with_valid_signature(self):
        self.app.config["PAYWAY_PUBLIC_API_ENABLED"] = False
        self.assertEqual(self.post('{"tran_id":"abc"}', signature("abc")).status_code, 503)
        self.hint.assert_not_called()

    def test_spring_top_level_sort_and_nested_json(self):
        body = '{"z":null,"tran_id":"abc","b":{"z":2,"a":[true,false,null,"shoe",10.00]},"a":0.01}'
        expected = '0.01{"z":2,"a":[true,false,null,"shoe",10]}abc'
        self.assertEqual(self.post(body, signature(expected)).status_code, 200)
        # Neither the PHP recursive-leaf format nor nested-key sorting is accepted.
        self.assertEqual(self.post(body, signature("0.0121shoe10abc")).status_code, 401)
        self.assertEqual(self.post(body, signature('0.01{"a":[true,false,null,"shoe",10],"z":2}abc')).status_code, 401)

    def test_spring_numeric_vectors(self):
        for token, rendered in (("10.00", "10"), ("-0.0", "0"), ("1e-5", "0.00001"),
                                ("1e14", "100000000000000"), ("123.4567890123456", "123.4567890123456"),
                                ("9223372036854775807", "9223372036854775807"),
                                ("9223372036854775808", "9223372036854775808")):
            body = ('{"a":' + token + ',"tran_id":"abc"}').encode()
            self.assertEqual(verify_callback(body, signature(rendered + "abc"), SECRET)["tran_id"], "abc")

    def test_nested_slashes_and_top_level_null_booleans(self):
        body = b'{"a":true,"b":false,"c":null,"d":["a/b",null,false],"tran_id":"abc"}'
        expected = r'1["a\/b",null,false]abc'
        self.assertEqual(self.post(body, signature(expected)).status_code, 200)

    def test_unicode_top_level_is_raw_nested_is_escaped(self):
        self.assertEqual(self.post('{"a":"\u1781\u17d2\u1798\u17c2\u179a","tran_id":"abc"}', signature("\u1781\u17d2\u1798\u17c2\u179aabc")).status_code, 200)
        body = json.dumps({"a": ["\u1781\u17d2\u1798\u17c2\u179a", "\U0001f600", "\u00e9/\n\u000b", r"\u000b"], "tran_id": "abc"})
        expected = r'["\u1781\u17d2\u1798\u17c2\u179a","\ud83d\ude00","\u00e9\/\n\u000B","\\u000b"]abc'
        self.assertEqual(self.post(body, signature(expected)).status_code, 200)

    def test_java_treemap_utf16_ordering(self):
        body = json.dumps({"\ue000": "last", "\U0001f600": "middle", "tran_id": "abc"})
        self.assertEqual(self.post(body, signature("abcmiddlelast")).status_code, 200)
