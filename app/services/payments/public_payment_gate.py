from urllib.parse import urlsplit

from flask import current_app

from app.exceptions.api_exception import PaymentGatewayUnavailableException
from app.services.payments.payway_client import PayWayClient


def require_public_payment_ready():
    """Explicit operator attestations, never toggled by application code/tests."""
    config = current_app.config
    for key in ("PAYWAY_PUBLIC_API_ENABLED", "PAYWAY_CALLBACK_APPROVED", "PAYWAY_SANDBOX_VERIFIED", "PAYWAY_WORKER_VERIFIED"):
        if config.get(key) is not True:
            raise PaymentGatewayUnavailableException("Public sandbox payments are not enabled")
    PayWayClient(config).ensure_configured()
    secret = config.get("PAYWAY_CALLBACK_SECRET")
    if not isinstance(secret, str) or not secret.strip():
        raise PaymentGatewayUnavailableException("PayWay callback authentication is not configured")
    path = urlsplit(config["PAYWAY_CALLBACK_URL"]).path
    if current_app.extensions.get("payway_callback_path") != path:
        raise PaymentGatewayUnavailableException("Configured payment callback is not registered")
