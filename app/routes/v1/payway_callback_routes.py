"""Callback path comes exclusively from PAYWAY_CALLBACK_URL.

HMAC-authenticated JSON callback field: tran_id. Financial claims require an
independent server-to-server check. See docs/payway_callback_security.md.
https://developer.payway.com.kh/aba-qr-api-3158158f0
"""
from collections import deque
import re
from threading import Lock
from time import monotonic
from urllib.parse import urlsplit

from flask import current_app, request

from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException
from app.services.payments.payway_callback_security import MAX_BODY_BYTES, SIGNATURE_HEADER, verify_callback
from app.services.payments.payment_service import PaymentService
from app.services.payments.public_payment_gate import require_public_payment_ready


def register_payway_callback(app):
    url = app.config.get("PAYWAY_CALLBACK_URL")
    if not url:
        return  # No invented fallback path.
    parsed = urlsplit(url)
    path = parsed.path
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password
            or parsed.query or parsed.fragment or not path.startswith("/") or path == "/"
            or any(char in path for char in "<>%")
            or any(rule.rule == path for rule in app.url_map.iter_rules())):
        raise ValueError("PAYWAY_CALLBACK_URL must have a unique literal HTTPS callback path")
    calls = deque()
    lock = Lock()

    def callback():
        require_public_payment_ready()
        # Bounded, per-worker protection; deployments also need a shared proxy
        # rate limit. No X-Forwarded-For trust or unbounded per-IP map.
        with lock:
            now = monotonic()
            while calls and calls[0] <= now - 60:
                calls.popleft()
            if len(calls) >= 120:
                return ApiResponse.error(message="Callback rate limit exceeded", status="Too Many Requests", http_status=429)
            calls.append(now)
        request.max_content_length = MAX_BODY_BYTES
        if not request.is_json:
            raise BadRequestException("Content type must be application/json")
        data = verify_callback(request.get_data(cache=False), request.headers.get(SIGNATURE_HEADER),
                               current_app.config.get("PAYWAY_CALLBACK_SECRET"))
        transaction_id = data.get("tran_id")
        if not isinstance(transaction_id, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", transaction_id):
            raise BadRequestException("Invalid callback transaction ID")
        PaymentService().callback_hint(transaction_id)
        # Do not disclose order/payment data to an unauthenticated callback.
        return ApiResponse.success(data=[], message="Notification checked")

    app.add_url_rule(path, "payway_callback", callback, methods=["POST"])
    app.extensions["payway_callback_path"] = path
