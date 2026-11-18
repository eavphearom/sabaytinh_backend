"""Explicit, read-only Sandbox transaction diagnostic. Never initializes or closes."""
import argparse
from decimal import Decimal, InvalidOperation
import json
import logging
import re

from app.services.payments.payway_client import PayWayClient, CONFIGURATION_FAILURE_REASONS
from app.services.payments.payment_strategy import PaymentContext


class VerificationOnlyClient(PayWayClient):
    def _post(self, path, payload):
        if path != self.CHECK_PATH:
            raise RuntimeError("Only Check Transaction is permitted")
        return super()._post(path, payload)

    def initialize(self, context):
        raise RuntimeError("Initialization is prohibited")

    def close(self, context):
        raise RuntimeError("Closure is prohibited")


class DiagnosticCapture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.result = dict(http_status=None, gateway_status_code=None,
            response_data_type=None, response_field_types={}, currency_fields={}, payment_status=None, payment_status_code=None, validation_failure_reason=None)

    def emit(self, record):
        # Consume only the client's fixed diagnostic templates, never formatted
        # arbitrary log messages or exceptions.
        if record.msg == "PayWay operation=%s http_status=%s gateway_code=%s data_type=%s fields=%s":
            operation, status, code, data_type, fields = record.args
            if operation == "verify":
                self.result.update(http_status=status, gateway_status_code=code,
                    response_data_type=data_type, response_field_types=fields)
        elif record.msg == "PayWay operation=%s currency_fields=%s":
            self.result["currency_fields"] = record.args[1]
        elif record.msg == "PayWay operation=%s payment_status=%s payment_status_code=%s":
            self.result["payment_status"] = record.args[1]
            self.result["payment_status_code"] = record.args[2]
        elif record.msg == "PayWay operation=%s validation_failure=%s":
            operation, reason = record.args
            if operation == "verify":
                self.result["validation_failure_reason"] = reason


def run_check(config, transaction_id, merchant_id, amount, currency, *, allow_live_check=False, enable_sandbox_for_check=False, check_config=False):
    capture = DiagnosticCapture()
    result = capture.result
    if not allow_live_check and not check_config:
        result["validation_failure_reason"] = "explicit_live_check_opt_in_required"
        return result, 2
    # Only a private copy used by this read-only client; never mutate Config/env.
    config = dict(config)
    if enable_sandbox_for_check:
        config["PAYWAY_SANDBOX_ENABLED"] = True
    try:
        VerificationOnlyClient(config, require_callback=False).ensure_configured()
    except Exception as exc:
        result["validation_failure_reason"] = CONFIGURATION_FAILURE_REASONS.get(str(exc), "invalid_configuration_structure")
        return result, 2
    try:
        amount = Decimal(amount)
        if (not re.fullmatch(r"[A-Za-z0-9_-]{1,20}", transaction_id)
                or merchant_id != config.get("PAYWAY_MERCHANT_ID") or not merchant_id
                or currency != "USD" or not amount.is_finite() or amount < Decimal("0.01")
                or amount != amount.quantize(Decimal("0.01"))):
            raise ValueError()
    except (ValueError, TypeError, InvalidOperation):
        result["validation_failure_reason"] = "invalid_original_context_or_merchant_mismatch"
        return result, 2
    if check_config:
        return result, 0
    context = PaymentContext(0, 0, transaction_id, merchant_id, amount, currency, "verification-only")
    logger = logging.getLogger("app.services.payments.payway_client")
    old = logger.handlers[:], logger.level, logger.propagate, logger.disabled
    logger.handlers = [capture]
    logger.setLevel(logging.WARNING)
    logger.propagate = False
    logger.disabled = False
    try:
        # No Flask app creation, database session, settlement, retries, or fallback.
        VerificationOnlyClient(config, require_callback=False).verify(context)
        return result, 0
    except Exception:
        result["validation_failure_reason"] = result["validation_failure_reason"] or "configuration_or_unclassified_failure"
        return result, 1
    finally:
        logger.handlers, logger.level, logger.propagate, logger.disabled = old


class SafeParser(argparse.ArgumentParser):
    def error(self, message):
        # argparse's default may echo invalid argument values.
        self.exit(2, "Invalid arguments. Use --help; original transaction context is required.\n")


def main(argv=None):
    parser = SafeParser(description=__doc__)
    parser.add_argument("--transaction-id", required=True)
    parser.add_argument("--merchant-id", required=True, help="Original merchant ID; must match local configuration")
    parser.add_argument("--amount", required=True, help="Exact original amount, e.g. 0.01")
    parser.add_argument("--currency", required=True, help="Original currency; this client supports USD only")
    parser.add_argument("--allow-live-check", action="store_true", help="Authorize one live Check request; no retries")
    parser.add_argument("--enable-sandbox-for-check", action="store_true",
        help="Enable sandbox only in this diagnostic client configuration copy")
    parser.add_argument("--check-config", action="store_true", help="Validate configuration/context only; never send HTTP")
    args = parser.parse_args(argv)
    config = {}
    if args.allow_live_check or args.check_config:
        try:
            # Load the backend .env deterministically, retaining OS env precedence.
            import os
            from pathlib import Path
            from dotenv import load_dotenv
            load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)
            for key, converter, default in (
                ("PAYWAY_CONNECT_TIMEOUT", float, "5"), ("PAYWAY_READ_TIMEOUT", float, "15"),
                ("PAYWAY_QR_LIFETIME_MINUTES", int, "15"), ("PAYWAY_LEASE_SECONDS", int, "90")):
                try:
                    converter(os.getenv(key, default))
                except (ValueError, TypeError):
                    result = DiagnosticCapture().result
                    result["validation_failure_reason"] = "invalid_config_number_" + key.lower()
                    print(json.dumps(result))
                    return 2
            from app.config import Config
            config = {key: getattr(Config, key) for key in dir(Config) if key.startswith("PAYWAY_")}
        except Exception:
            result = DiagnosticCapture().result
            result["validation_failure_reason"] = "configuration_load_failed"
            print(json.dumps(result))
            return 2
    result, code = run_check(config, args.transaction_id, args.merchant_id, args.amount,
        args.currency, allow_live_check=args.allow_live_check,
        enable_sandbox_for_check=args.enable_sandbox_for_check, check_config=args.check_config)
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
