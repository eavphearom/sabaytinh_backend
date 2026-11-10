"""Explicit opt-in smoke test. Creates only a sandbox transaction, then closes it."""
from decimal import Decimal
import os
import sys
import unittest
from uuid import uuid4

from app.config import Config
from app.services.payments.payment_strategy import PaymentContext, GatewayResult
from app.services.payments.payway_client import PayWayClient


def _matches(result, context):
    return (isinstance(result, GatewayResult)
            and result.transaction_id == context.transaction_id
            and result.merchant_id == context.merchant_id
            and result.amount == context.amount and result.currency == context.currency)


def _cleanup_transaction(client, context):
    """Bounded cleanup; uncertainty and paid evidence always require review."""
    try:
        result = client.verify(context)
    except Exception:
        return "UNRESOLVED_VERIFICATION"
    if not _matches(result, context):
        return "UNRESOLVED_VERIFICATION"
    if result.status == "APPROVED":
        return "PAID_MANUAL_REVIEW"  # Never close/refund a verified payment here.
    if result.status not in ("PENDING", "CANCELLED", "DECLINED"):
        return "UNRESOLVED_VERIFICATION"
    try:
        closed = client.close(context)
        if _matches(closed, context) and closed.status == "CLOSED":
            # Preserve the smoke test's PENDING expectation while reporting
            # confirmed cleanup truthfully for other nonpaid outcomes.
            return "CLOSED_CONFIRMED" if result.status == "PENDING" else "CLOSED_CONFIRMED_UNEXPECTED_STATUS"
    except Exception:
        pass
    # Closure may have succeeded remotely despite a lost response. A check
    # can identify a racing payment, but CANCELLED alone is not close evidence.
    try:
        result = client.verify(context)
        if _matches(result, context) and result.status == "APPROVED":
            return "PAID_MANUAL_REVIEW"
    except Exception:
        pass
    return "UNRESOLVED_CLOSURE"


def run_sandbox_smoke(client, context):
    client.ensure_configured()  # Validate the selected client mode before network I/O.
    initialized = False
    may_exist = False
    outcome = "NOT_ATTEMPTED"
    try:
        # Record the stable ID BEFORE initialize: a timeout is ambiguous and a
        # hard process termination cannot run finally. Capture stderr for recovery.
        may_exist = True
        print(f"Sandbox transaction_id={context.transaction_id} MAY_EXIST", file=sys.stderr, flush=True)
        try:
            result = client.initialize(context)
            initialized = _matches(result, context) and result.status == "READY"
        except Exception:
            # Do not expose exceptions, raw responses, credentials or QR data.
            initialized = False
    finally:
        if may_exist:
            outcome = _cleanup_transaction(client, context)
            print(f"Sandbox transaction_id={context.transaction_id} {outcome}", file=sys.stderr, flush=True)
    if not initialized or outcome != "CLOSED_CONFIRMED":
        phase = "QR initialization failed or unconfirmed" if not initialized else "Cleanup requires manual follow-up"
        raise AssertionError(f"{phase}; transaction_id={context.transaction_id}; cleanup={outcome}") from None


@unittest.skipUnless(
    os.getenv("PAYWAY_RUN_SANDBOX_TESTS") == "true"
    and Config.PAYWAY_SANDBOX_ENABLED and Config.PAYWAY_MERCHANT_ID
    and Config.PAYWAY_API_KEY and Config.PAYWAY_CALLBACK_URL,
    "Sandbox smoke test requires explicit opt-in and configured sandbox credentials",
)
class PayWaySandboxTests(unittest.TestCase):
    def test_initialize_verify_and_close_sandbox_transaction(self):
        config = {name: getattr(Config, name) for name in dir(Config) if name.startswith("PAYWAY_")}
        client = PayWayClient(config)
        context = PaymentContext(0, 0, uuid4().hex[:20], Config.PAYWAY_MERCHANT_ID,
                                 Decimal("0.01"), "USD", "sandbox-smoke-test")
        run_sandbox_smoke(client, context)
