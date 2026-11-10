"""Verify the supplied Spring PayWayHashService callback representation.

Nested values use compact JSON, not the official PHP recursive-leaf example.
See docs/payway_callback_security.md for outstanding protocol confirmation.
"""
import base64
import binascii
import hashlib
import hmac
import json
from decimal import Decimal, DecimalException

from app.exceptions.api_exception import (
    BadRequestException, UnauthorizedException, PaymentGatewayUnavailableException,
)


MAX_BODY_BYTES = 16 * 1024
SIGNATURE_HEADER = "X-PayWay-HMAC-SHA512"


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(value):
    raise ValueError("Nonfinite JSON number")


def _number(value):
    # BigDecimal.stripTrailingZeros().toPlainString(), without rounding to the
    # Python decimal context precision or passing through binary floats.
    if not value.is_finite() or abs(value.adjusted()) > 1024:
        raise ValueError("Unsupported callback number")
    if value.is_zero():
        return "0"
    result = format(value, "f")
    return result.rstrip("0").rstrip(".") if "." in result else result


def _string(value):
    value.encode("utf-8")  # Reject unpaired surrogate escapes.
    escapes = {34: '\\"', 92: '\\\\', 47: '\\/', 8: '\\b', 12: '\\f',
               10: '\\n', 13: '\\r', 9: '\\t'}
    units = value.encode("utf-16-be")
    result = ['"']
    for index in range(0, len(units), 2):
        code = int.from_bytes(units[index:index + 2], "big")
        if code in escapes:
            result.append(escapes[code])
        elif code < 32:
            result.append(f"\\u{code:04X}")  # Jackson's control escapes.
        elif code > 127:
            result.append(f"\\u{code:04x}")  # Spring's explicit Unicode loop.
        else:
            result.append(chr(code))
    return "".join(result) + '"'


def _value(value, depth=0, nested=False):
    if depth > 32:
        raise ValueError("JSON nesting limit exceeded")
    if value is None:
        return "null" if nested else ""
    if isinstance(value, bool):
        return ("true" if value else "false") if nested else ("1" if value else "")
    if isinstance(value, Decimal):
        return _number(value)
    if isinstance(value, str):
        value.encode("utf-8")
        return _string(value) if nested else value
    if isinstance(value, list):
        return "[" + ",".join(_value(child, depth + 1, True) for child in value) + "]"
    if isinstance(value, dict):
        return "{" + ",".join(_string(key) + ":" + _value(child, depth + 1, True)
                              for key, child in value.items()) + "}"
    raise ValueError("Unsupported callback value")


def verify_callback(raw_body, signature, secret):
    """Return parsed data only after successful constant-time HMAC comparison."""
    if not isinstance(secret, str) or not secret.strip():
        raise PaymentGatewayUnavailableException("PayWay callback authentication is not configured")
    if not isinstance(signature, str) or len(signature) != 88:
        raise UnauthorizedException("Invalid PayWay callback signature")
    try:
        supplied = base64.b64decode(signature, validate=True)
        if len(supplied) != 64 or base64.b64encode(supplied).decode("ascii") != signature:
            raise ValueError("Noncanonical signature")
    except (ValueError, binascii.Error):
        raise UnauthorizedException("Invalid PayWay callback signature") from None
    if len(raw_body) > MAX_BODY_BYTES:
        from werkzeug.exceptions import RequestEntityTooLarge
        raise RequestEntityTooLarge()
    try:
        data = json.loads(raw_body.decode("utf-8"), object_pairs_hook=_object,
                          parse_constant=_reject_constant, parse_int=Decimal, parse_float=Decimal)
        if not isinstance(data, dict):
            raise ValueError("Callback must be an object")
        keys = sorted(data, key=lambda key: key.encode("utf-16-be"))
        message = "".join(_value(data[key]) for key in keys).encode("utf-8")
    except (ValueError, UnicodeError, RecursionError, OverflowError, DecimalException):
        raise BadRequestException("Invalid PayWay callback JSON") from None
    expected = hmac.new(secret.encode("utf-8"), message, hashlib.sha512).digest()
    if not hmac.compare_digest(expected, supplied):
        raise UnauthorizedException("Invalid PayWay callback signature")
    return data
