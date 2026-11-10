"""PayWay sandbox protocol, verified against official API specifications.

https://developer.payway.com.kh/qr-api-14530840e0.md
https://developer.payway.com.kh/check-transaction-14530826e0.md
https://developer.payway.com.kh/close-transaction-14530822e0.md

Responses are authenticated by HTTPS to the fixed sandbox host, in response to
merchant-scoped signed requests. PayWay does not document response signatures
for these APIs. Callback payloads are NOT payment evidence.
"""
import base64
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
import hashlib
import hmac
import http.client
import json
import math
import re
import ssl
from urllib.parse import urlsplit

from app.services.payments.payment_strategy import GatewayError, GatewayResult
from app.utils.date_util import DateUtil


class PayWayClient:
    HOST = "checkout-sandbox.payway.com.kh"
    QR_PATH = "/api/payment-gateway/v1/payments/generate-qr"
    CHECK_PATH = "/api/payment-gateway/v1/payments/check-transaction-2"
    CLOSE_PATH = "/api/payment-gateway/v1/payments/close-transaction"
    QR_SIGN_FIELDS = (
        "req_time", "merchant_id", "tran_id", "amount", "items", "first_name",
        "last_name", "email", "phone", "purchase_type", "payment_option",
        "callback_url", "return_deeplink", "currency", "custom_fields",
        "return_params", "payout", "lifetime", "qr_image_template",
    )

    def __init__(self, config, *, require_callback=True):
        self.config = config
        # Only explicit internal probes may omit the optional QR API field.
        # Application services/public readiness retain the stricter default.
        self.require_callback = require_callback

    def ensure_configured(self):
        c = self.config
        if c.get("PAYWAY_SANDBOX_ENABLED") is not True:
            raise GatewayError("PayWay sandbox is disabled")
        if c.get("PAYWAY_BASE_URL", "").rstrip("/") != "https://" + self.HOST:
            raise GatewayError("Only the official PayWay sandbox host is allowed")
        merchant = c.get("PAYWAY_MERCHANT_ID")
        if not isinstance(merchant, str) or not merchant.strip() or len(merchant) > 20:
            raise GatewayError("Sandbox merchant ID is missing or invalid")
        if not isinstance(c.get("PAYWAY_API_KEY"), str) or not c["PAYWAY_API_KEY"].strip():
            raise GatewayError("Sandbox API key is required")
        callback = c.get("PAYWAY_CALLBACK_URL") or ""
        url = urlsplit(callback)
        if (self.require_callback or callback) and (
                url.scheme != "https" or not url.hostname or url.username or url.password or url.fragment):
            raise GatewayError("A public HTTPS callback URL is required")
        if len(base64.b64encode(callback.encode())) > 255:
            raise GatewayError("Encoded callback URL exceeds gateway limit")
        connect, read = c.get("PAYWAY_CONNECT_TIMEOUT", 5), c.get("PAYWAY_READ_TIMEOUT", 15)
        if any(not isinstance(t, (int, float)) or not math.isfinite(t) or not 0 < t <= 60 for t in (connect, read)):
            raise GatewayError("Invalid gateway timeouts")
        lease = c.get("PAYWAY_LEASE_SECONDS", 90)
        if type(lease) is not int or not 3 * (connect + read) + 10 <= lease <= 600:
            raise GatewayError("Lease must cover verification and closure timeouts")
        lifetime = c.get("PAYWAY_QR_LIFETIME_MINUTES", 15)
        if type(lifetime) is not int or not 3 <= lifetime <= 172800:
            raise GatewayError("Invalid QR lifetime")

    def _payload(self, context):
        self.ensure_configured()
        if context.merchant_id != self.config["PAYWAY_MERCHANT_ID"]:
            raise GatewayError("Merchant mismatch")
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", context.transaction_id)
                or context.currency != "USD" or not isinstance(context.amount, Decimal)
                or not context.amount.is_finite() or context.amount < Decimal("0.01")
                or context.amount != context.amount.quantize(Decimal("0.01"))):
            raise GatewayError("Invalid gateway transaction parameters")
        return {"req_time": datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S"),
                "merchant_id": context.merchant_id, "tran_id": context.transaction_id}

    def _sign(self, payload, fields):
        message = "".join(str(payload.get(key, "")) for key in fields)
        return base64.b64encode(hmac.new(
            self.config["PAYWAY_API_KEY"].encode(), message.encode(), hashlib.sha512,
        ).digest()).decode()

    def _post(self, path, payload):
        # Decimal numbers retain the same lexical representation used in signing.
        body = "{" + ",".join(json.dumps(k) + ":" + (
            format(v, "f") if isinstance(v, Decimal) else json.dumps(v)
        ) for k, v in payload.items()) + "}"
        connection = http.client.HTTPSConnection(
            self.HOST, timeout=self.config.get("PAYWAY_CONNECT_TIMEOUT", 5),
            context=ssl.create_default_context(),
        )
        try:
            connection.connect()
            connection.sock.settimeout(self.config.get("PAYWAY_READ_TIMEOUT", 15))
            connection.request("POST", path, body.encode(), {"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = response.read(2_000_001)
            if response.status != 200 or len(raw) > 2_000_000:
                raise GatewayError("Gateway request failed")
            result = json.loads(raw, parse_float=Decimal,
                                parse_constant=lambda _: None)
            if not isinstance(result, dict):
                raise GatewayError("Malformed gateway response")
            return result
        except (OSError, http.client.HTTPException, ValueError):
            raise GatewayError("Gateway unavailable or returned invalid JSON") from None
        finally:
            connection.close()

    @staticmethod
    def _amount(value, expected):
        try:
            if isinstance(value, bool) or value is None:
                raise InvalidOperation
            amount = Decimal(str(value))
            if not amount.is_finite() or amount != expected:
                raise InvalidOperation
        except (InvalidOperation, ValueError):
            raise GatewayError("Gateway amount mismatch") from None

    @staticmethod
    def _status(response, code, transaction_id=None):
        status = response.get("status")
        if not isinstance(status, dict) or status.get("code") != code:
            raise GatewayError("Gateway rejected request or returned malformed status")
        if transaction_id is not None and status.get("tran_id") != transaction_id:
            raise GatewayError("Gateway transaction mismatch")

    def initialize(self, context):
        payload = self._payload(context)
        lifetime = self.config.get("PAYWAY_QR_LIFETIME_MINUTES", 15)
        payload.update(amount=context.amount, currency=context.currency,
                       purchase_type="purchase", payment_option="abapay_khqr",
                       lifetime=lifetime, qr_image_template="template3_color")
        callback = self.config.get("PAYWAY_CALLBACK_URL")
        if callback:
            payload["callback_url"] = base64.b64encode(callback.encode()).decode()
        payload["hash"] = self._sign(payload, self.QR_SIGN_FIELDS)
        # The documented response has no expiry field: retain the requested
        # lifetime conservatively from the start of the request.
        expires = DateUtil.now() + timedelta(minutes=lifetime)
        response = self._post(self.QR_PATH, payload)
        self._status(response, "0")
        self._amount(response.get("amount"), context.amount)
        if response.get("currency") != context.currency:
            raise GatewayError("Gateway currency mismatch")
        for key in ("qrString", "qrImage", "abapay_deeplink"):
            if not isinstance(response.get(key), str) or not response[key]:
                raise GatewayError("Missing gateway QR fields")
        if (not response["qrImage"].startswith("data:image/png;base64,")
                or not response["abapay_deeplink"].startswith("abamobilebank://")):
            raise GatewayError("Invalid gateway QR format")
        return GatewayResult(context.transaction_id, context.merchant_id, context.amount,
                             context.currency, "READY", qr_string=response["qrString"],
                             qr_image=response["qrImage"], abapay_deeplink=response["abapay_deeplink"],
                             expires_at=expires)

    def verify(self, context):
        payload = self._payload(context)
        payload["hash"] = self._sign(payload, ("req_time", "merchant_id", "tran_id"))
        response = self._post(self.CHECK_PATH, payload)
        self._status(response, "00", context.transaction_id)
        data = response.get("data")
        if not isinstance(data, dict):
            raise GatewayError("Missing transaction details")
        self._amount(data.get("original_amount"), context.amount)
        self._amount(data.get("total_amount"), context.amount)
        if data.get("payment_currency") != context.currency:
            raise GatewayError("Gateway currency mismatch")
        status = data.get("payment_status")
        codes = {"APPROVED": 0, "PENDING": 2, "DECLINED": 3, "CANCELLED": 7}
        code = data.get("payment_status_code")
        if status not in codes or type(code) is not int or code != codes[status]:
            raise GatewayError("Unsupported or contradictory gateway transaction status")
        reference = None
        if status == "APPROVED":
            self._amount(data.get("payment_amount"), context.amount)
            self._amount(data.get("refund_amount"), Decimal("0"))
            reference = data.get("apv")
            if not isinstance(reference, str) or not 1 <= len(reference) <= 255:
                raise GatewayError("Missing approval reference")
        return GatewayResult(context.transaction_id, context.merchant_id, context.amount,
                             context.currency, status, reference=reference)

    def close(self, context):
        payload = self._payload(context)
        payload["hash"] = self._sign(payload, ("req_time", "merchant_id", "tran_id"))
        self._status(self._post(self.CLOSE_PATH, payload), "00", context.transaction_id)
        return GatewayResult(context.transaction_id, context.merchant_id, context.amount,
                             context.currency, "CLOSED")
