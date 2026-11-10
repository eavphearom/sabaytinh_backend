"""Explicit live sandbox probe without a callback URL; never make a payment.

The official generate-qr schema marks callback_url optional. Reuse the existing
bounded verification/closure recovery; no public routes or database writes.
"""
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from app.config import Config
from app.services.payments.payment_strategy import PaymentContext
from app.services.payments.payway_client import PayWayClient
from tests.test_payway_sandbox import run_sandbox_smoke


def run_qr_only_probe(config):
    # Omit the optional field deliberately even if a callback is configured in
    # the caller's environment. Do not mutate Config or readiness flags.
    probe_config = dict(config)
    probe_config["PAYWAY_CALLBACK_URL"] = ""
    client = PayWayClient(probe_config, require_callback=False)
    context = PaymentContext(0, 0, uuid4().hex[:20], probe_config.get("PAYWAY_MERCHANT_ID"),
                             Decimal("0.01"), "USD", "sandbox-qr-only-test")
    run_sandbox_smoke(client, context)


@unittest.skipUnless(
    os.getenv("PAYWAY_RUN_QR_ONLY_TESTS") == "true"
    and Config.PAYWAY_SANDBOX_ENABLED and Config.PAYWAY_MERCHANT_ID and Config.PAYWAY_API_KEY,
    "QR-only sandbox test requires explicit opt-in, sandbox enablement and credentials",
)
class PayWaySandboxQROnlyTests(unittest.TestCase):
    def test_generate_verify_and_close_without_callback(self):
        config = {name: getattr(Config, name) for name in dir(Config) if name.startswith("PAYWAY_")}
        run_qr_only_probe(config)
