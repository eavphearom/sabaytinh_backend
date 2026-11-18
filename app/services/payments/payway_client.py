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
from enum import Enum
import hashlib
import hmac
import http.client
import json
import logging
from functools import wraps
import math
import re
import ssl
from urllib.parse import urlsplit

from app.services.payments.payment_strategy import GatewayError, GatewayResult
from app.utils.date_util import DateUtil
from app.workers.execution_scope import external_timeouts, read_response, WorkerStopped, active_execution, set_stage


logger = logging.getLogger(__name__)


CONFIGURATION_FAILURE_REASONS = {
    "PayWay sandbox is disabled": "sandbox_disabled",
    "Only the official PayWay sandbox host is allowed": "invalid_sandbox_host",
    "Sandbox merchant ID is missing or invalid": "invalid_merchant_configuration",
    "Sandbox API key is required": "api_key_missing",
    "A public HTTPS callback URL is required": "invalid_callback_url",
    "Encoded callback URL exceeds gateway limit": "callback_url_too_long",
    "Invalid gateway timeouts": "invalid_gateway_timeouts",
    "Lease must cover verification and closure timeouts": "invalid_gateway_lease",
    "Invalid QR lifetime": "invalid_qr_lifetime",
}


def diagnostic_operation(operation):
    """Log only local allowlisted reasons, never arbitrary exception text."""
    reasons = {
        **CONFIGURATION_FAILURE_REASONS,
        "Gateway amount mismatch": "amount_mismatch",
        "Gateway currency mismatch": "currency_mismatch",
        "Gateway transaction mismatch": "transaction_mismatch",
        "Gateway rejected request or returned malformed status": "gateway_status_rejected",
        "Missing transaction details": "missing_transaction_details",
        "Unsupported or contradictory gateway transaction status": "contradictory_payment_status",
        "Missing approval reference": "missing_approval_reference",
        "Missing gateway QR fields": "missing_qr_fields",
        "Invalid gateway QR format": "invalid_qr_format",
        "Gateway request failed": "http_or_size_failure",
        "Malformed gateway response": "invalid_response_shape",
        "Gateway unavailable or returned invalid JSON": "transport_or_json_failure",
    }
    def decorate(method):
        @wraps(method)
        def wrapped(*args, **kwargs):
            try:
                return method(*args, **kwargs)
            except WorkerStopped as exc:
                scope = active_execution.get()
                logger.warning("PayWay operation=%s worker_abort=%s diagnostics=%s", operation,
                               exc.reason, scope.diagnostics() if scope else {})
                raise
            except Exception as exc:
                reason = reasons.get(str(exc), "configuration_or_unclassified_failure") if isinstance(exc, GatewayError) else "unclassified_failure"
                logger.warning("PayWay operation=%s validation_failure=%s", operation, reason)
                if not isinstance(exc, GatewayError):
                    kind = {TypeError: "type_error", AttributeError: "attribute_error",
                            ValueError: "value_error"}.get(type(exc), "unexpected_client_error")
                    scope = active_execution.get()
                    logger.warning("PayWay operation=%s operational_failure=%s diagnostics=%s",
                                   operation, kind, scope.diagnostics() if scope else {})
                raise
        return wrapped
    return decorate


def response_diagnostic(operation, http_status, response):
    """Only numeric protocol codes and fixed field/type names may leave the client."""
    status = response.get("status") if isinstance(response, dict) else None
    data = response.get("data") if isinstance(response, dict) else None
    code = status.get("code") if isinstance(status, dict) else None
    code = str(code) if type(code) in (str, int) and re.fullmatch(r"[0-9]{1,6}", str(code)) else "missing_or_unrecognized"
    known = ("original_amount", "total_amount", "payment_amount", "refund_amount", "payment_currency", "original_currency", "payment_status", "payment_status_code", "apv")
    shapes = {key: (type(data[key]).__name__ if key in data else "missing") for key in known} if isinstance(data, dict) else {}
    logger.warning("PayWay operation=%s http_status=%s gateway_code=%s data_type=%s fields=%s",
        operation, http_status, code, type(data).__name__, shapes)


def currency_diagnostic(data, expected):
    def describe(key):
        if key not in data:
            return {"format": "missing", "matches_expected": False}
        value = data[key]
        if value is None:
            kind = "null"
        elif not isinstance(value, str):
            kind = "non_string"
        elif not value:
            kind = "empty"
        elif not re.fullmatch(r"[A-Z]{3}", value):
            kind = "invalid_format"
        elif value not in ("USD", "KHR"):
            kind = "unsupported_code"
        else:
            kind = "supported_code"
        return {"format": kind, "matches_expected": value == expected}
    logger.warning("PayWay operation=%s currency_fields=%s", "verify",
        {key: describe(key) for key in ("original_currency", "payment_currency")})


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
        # QR callback delivery is optional; services and the worker explicitly
        # allow omission. Callback readiness uses the stricter default.
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
        set_stage("gateway_admission")
        # Decimal numbers retain the same lexical representation used in signing.
        body = "{" + ",".join(json.dumps(k) + ":" + (
            format(v, "f") if isinstance(v, Decimal) else json.dumps(v)
        ) for k, v in payload.items()) + "}"
        connect_timeout, read_timeout = external_timeouts(
            self.config.get("PAYWAY_CONNECT_TIMEOUT", 5), self.config.get("PAYWAY_READ_TIMEOUT", 15))
        connection = http.client.HTTPSConnection(
            self.HOST, timeout=connect_timeout,
            context=ssl.create_default_context(),
        )
        operation = {self.QR_PATH: "initialize", self.CHECK_PATH: "verify", self.CLOSE_PATH: "close"}.get(path, "unknown")
        try:
            set_stage("gateway_connect")
            connection.connect()
            connection.sock.settimeout(read_timeout)
            set_stage("gateway_request")
            connection.request("POST", path, body.encode(), {"Content-Type": "application/json"})
            set_stage("gateway_headers")
            response = connection.getresponse()
            set_stage("gateway_body")
            raw = read_response(response, connection, 2_000_001, read_timeout)
            set_stage("gateway_validation")
            if len(raw) > 2_000_000:
                response_diagnostic(operation, response.status, None)
                raise GatewayError("Gateway request failed")
            try:
                result = json.loads(raw, parse_float=Decimal, parse_constant=lambda _: None)
            except ValueError:
                response_diagnostic(operation, response.status, None)
                raise
            response_diagnostic(operation, response.status, result)
            if response.status != 200:
                raise GatewayError("Gateway request failed")
            if not isinstance(result, dict):
                raise GatewayError("Malformed gateway response")
            return result
        except (OSError, http.client.HTTPException, ValueError) as exc:
            failure = "timeout" if isinstance(exc, TimeoutError) else (
                "invalid_json" if isinstance(exc, ValueError) else "transport_error")
            scope = active_execution.get()
            logger.warning("PayWay operation=%s transport_failure=%s diagnostics=%s",
                           operation, failure, scope.diagnostics() if scope else {})
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

    @diagnostic_operation("initialize")
    def initialize(self, context):
        payload = self._payload(context)
        lifetime = self.config.get("PAYWAY_QR_LIFETIME_MINUTES", 15)
        # SQLAlchemy returns Currency(str, Enum): str(member) is "Currency.USD",
        # while JSON encodes "USD". Sign exactly the value sent on the wire.
        currency = context.currency.value if isinstance(context.currency, Enum) else context.currency
        payload.update(amount=context.amount, currency=currency,
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

    @diagnostic_operation("verify")
    def verify(self, context):
        payload = self._payload(context)
        payload["hash"] = self._sign(payload, ("req_time", "merchant_id", "tran_id"))
        response = self._post(self.CHECK_PATH, payload)
        self._status(response, "00", context.transaction_id)
        data = response.get("data")
        if not isinstance(data, dict):
            raise GatewayError("Missing transaction details")
        currency_diagnostic(data, context.currency)
        status = data.get("payment_status")
        codes = {"APPROVED": 0, "PENDING": 2, "DECLINED": 3, "CANCELLED": 7}
        code = data.get("payment_status_code")
        known_status = status if isinstance(status, str) and status in codes else "missing_or_unsupported"
        known_code = code if type(code) is int and code in codes.values() else "missing_or_unsupported"
        logger.warning("PayWay operation=%s payment_status=%s payment_status_code=%s",
            "verify", known_status, known_code)
        if known_status == "missing_or_unsupported" or type(code) is not int or code != codes[status]:
            raise GatewayError("Unsupported or contradictory gateway transaction status")
        self._amount(data.get("original_amount"), context.amount)
        self._amount(data.get("total_amount"), context.amount)
        # Check Transaction does not require original_currency. If supplied,
        # contradictory original-currency evidence must still fail closed.
        if "original_currency" in data and data["original_currency"] != context.currency:
            raise GatewayError("Gateway currency mismatch")
        # An unpaid PENDING transaction may have no payer currency yet. Null,
        # malformed or nonempty mismatched values are not covered by this case.
        pending_without_payer_currency = status == "PENDING" and (
            "payment_currency" not in data or data["payment_currency"] == "")
        if not pending_without_payer_currency and data.get("payment_currency") != context.currency:
            # Cross-currency approval needs a separately verified conversion
            # contract; never compare a KHR payer amount as if it were USD.
            raise GatewayError("Gateway currency mismatch")
        reference = None
        if status != "APPROVED":
            # An approval reference or refund contradicts nonpaid evidence.
            # Do not discard it and authorize renewal from the status alone.
            if data.get("apv") not in (None, ""):
                raise GatewayError("Unsupported or contradictory gateway transaction status")
            if "refund_amount" in data:
                self._amount(data["refund_amount"], Decimal("0"))
        if status == "APPROVED":
            self._amount(data.get("payment_amount"), context.amount)
            self._amount(data.get("refund_amount"), Decimal("0"))
            reference = data.get("apv")
            if not isinstance(reference, str) or not 1 <= len(reference) <= 255:
                raise GatewayError("Missing approval reference")
        return GatewayResult(context.transaction_id, context.merchant_id, context.amount,
                             context.currency, status, reference=reference)

    @diagnostic_operation("close")
    def close(self, context):
        payload = self._payload(context)
        payload["hash"] = self._sign(payload, ("req_time", "merchant_id", "tran_id"))
        self._status(self._post(self.CLOSE_PATH, payload), "00", context.transaction_id)
        return GatewayResult(context.transaction_id, context.merchant_id, context.amount,
                             context.currency, "CLOSED")
