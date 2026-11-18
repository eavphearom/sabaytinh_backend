"""Explicit Sandbox cleanup: Check, at most one Close, then Check. No QR or DB writes."""
import copy
from decimal import Decimal
import json
import logging
from pathlib import Path
from dotenv import load_dotenv

from app.payway_verify_only import DiagnosticCapture, SafeParser, run_check
from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import PaymentContext, GatewayResult


class CloseOnlyClient(PayWayClient):
    def initialize(self, context):
        raise RuntimeError("QR initialization is prohibited")

    def _post(self, path, payload):
        if path not in (self.CHECK_PATH, self.CLOSE_PATH):
            raise RuntimeError("Only Check and Close are permitted")
        return super()._post(path, payload)


class StageCapture(DiagnosticCapture):
    def emit(self, record):
        if isinstance(record.args, tuple) and record.args and record.args[0] == "close":
            record = copy.copy(record)
            record.args = ("verify", *record.args[1:])
        super().emit(record)


def matches(result, context):
    return (isinstance(result, GatewayResult) and result.transaction_id == context.transaction_id
        and result.merchant_id == context.merchant_id and result.amount == context.amount
        and result.currency == context.currency)


def run_close(config, transaction_id, merchant_id, amount, currency, *, allow_live_close=False,
              enable_sandbox_for_close=False):
    output = dict(outcome="NOT_ATTEMPTED", close_api_confirmed=False,
        final_status=None, final_cancelled_confirmed=False, diagnostics={})
    if not allow_live_close:
        output["outcome"] = "EXPLICIT_LIVE_CLOSE_OPT_IN_REQUIRED"
        return output, 2
    config = dict(config)
    if enable_sandbox_for_close:
        config["PAYWAY_SANDBOX_ENABLED"] = True
    preflight, code = run_check(config, transaction_id, merchant_id, amount, currency, check_config=True)
    if code:
        output["outcome"] = "CONFIGURATION_OR_CONTEXT_REJECTED"
        output["diagnostics"]["preflight"] = preflight
        return output, 2
    context = PaymentContext(0, 0, transaction_id, merchant_id, Decimal(amount), currency, "close-only")
    client = CloseOnlyClient(config, require_callback=False)
    logger = logging.getLogger("app.services.payments.payway_client")
    old = logger.handlers[:], logger.level, logger.propagate, logger.disabled
    logger.setLevel(logging.WARNING); logger.propagate = False; logger.disabled = False

    def call(stage, operation):
        capture = StageCapture(); logger.handlers = [capture]
        try:
            result = operation(context)
            if not matches(result, context):
                capture.result["validation_failure_reason"] = "evidence_mismatch"
                return None
            return result
        except Exception:
            capture.result["validation_failure_reason"] = capture.result["validation_failure_reason"] or "unclassified_failure"
            return None
        finally:
            output["diagnostics"][stage] = capture.result

    try:
        initial = call("before_close", client.verify)
        if initial is None or initial.status not in ("PENDING", "DECLINED", "CANCELLED"):
            output["outcome"] = "PAID_MANUAL_REVIEW" if initial and initial.status == "APPROVED" else "UNRESOLVED_VERIFICATION"
            return output, 1
        # No user interaction or retries between fresh verification and Close.
        closed = call("close", client.close)
        output["close_api_confirmed"] = bool(closed and closed.status == "CLOSED")
        # A lost Close response is ambiguous. Only read again; never retry Close.
        final = call("after_close", client.verify)
        output["final_status"] = final.status if final and final.status in ("PENDING", "APPROVED", "DECLINED", "CANCELLED") else None
        if final and final.status == "APPROVED":
            output["outcome"] = "PAID_MANUAL_REVIEW"
        elif output["close_api_confirmed"] and final and final.status == "CANCELLED":
            output.update(outcome="CLOSE_ACCEPTED_AND_CANCELLED_VERIFIED", final_cancelled_confirmed=True)
            return output, 0
        else:
            output["outcome"] = ("CLOSE_ACCEPTED_FINAL_STATUS_UNCONFIRMED" if output["close_api_confirmed"]
                else "UNRESOLVED_CLOSURE")
        return output, 1
    finally:
        logger.handlers, logger.level, logger.propagate, logger.disabled = old


def main(argv=None):
    parser = SafeParser(description=__doc__)
    for name in ("transaction-id", "merchant-id", "amount", "currency"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--allow-live-close", action="store_true", help="Authorize Check, one Close if nonpaid, and final Check")
    parser.add_argument("--enable-sandbox-for-close", action="store_true", help="Sandbox enablement only in this client's private config copy")
    args = parser.parse_args(argv)
    config = {}
    if args.allow_live_close:
        try:
            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
            from app.config import Config
            config = {key: getattr(Config, key) for key in dir(Config) if key.startswith("PAYWAY_")}
        except Exception:
            print(json.dumps({"outcome": "CONFIGURATION_LOAD_FAILED"}))
            return 2
    result, code = run_close(config, args.transaction_id, args.merchant_id, args.amount, args.currency,
        allow_live_close=args.allow_live_close, enable_sandbox_for_close=args.enable_sandbox_for_close)
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
