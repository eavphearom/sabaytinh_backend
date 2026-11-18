"""Operator-only Sandbox checkout harness. No public routes or readiness changes."""
import argparse
import html
import json
import os
from pathlib import Path

from app.services.checkout_service import CheckoutService
from app.services.payments.payment_service import PaymentService
from app.services.payments.payway_client import PayWayClient
from app.workers.payment_worker import PaymentWorker


def prepare_config(app):
    # Refuse an already enabled public test environment; never change its flags.
    if any(app.config.get(key) for key in (
        "PAYWAY_PUBLIC_API_ENABLED", "PAYWAY_SANDBOX_VERIFIED",
        "PAYWAY_WORKER_VERIFIED", "PAYWAY_CALLBACK_APPROVED",
    )):
        raise ValueError("Public readiness must remain disabled")
    app.config["PAYWAY_SANDBOX_ENABLED"] = True  # This CLI process only.
    PayWayClient(app.config, require_callback=False).ensure_configured()


def create_probe(customer_id, payload, receipt):
    """Exclusive append-only receipt prevents accidental repeat of this run.

    Not a distributed idempotency mechanism: a crash during checkout requires
    manual DB inspection even if the committed IDs could not be journaled.
    """
    receipt = Path(receipt)
    with receipt.open("x", encoding="utf-8") as journal:
        def record(data):
            journal.write(json.dumps(data) + "\n")
            journal.flush()
            os.fsync(journal.fileno())

        record({"stage": "STARTED_DO_NOT_REPEAT", "customer_id": customer_id})
        ids = CheckoutService().checkout(customer_id, payload)
        record({"stage": "ORDER_COMMITTED", **ids})
        # Checkout already committed. Failure must preserve its stock reservation.
        try:
            result = PaymentService().initialize(ids["payment_id"])
        except Exception:
            record({"stage": "INITIALIZATION_UNRESOLVED", **ids})
            return {"outcome": "INITIALIZATION_UNRESOLVED", **ids}, 1
        record({"stage": "INITIALIZATION_RETURNED", **ids})
        image = result.get("qr_image")
        if not isinstance(image, str) or not image.startswith("data:image/png;base64,"):
            return {"outcome": "QR_DISPLAY_UNAVAILABLE_DO_NOT_REINITIALIZE", **ids}, 1
        # QR is deliberately written only to a private local artifact, never logs.
        qr_file = receipt.with_suffix(".qr.html")
        with qr_file.open("x", encoding="utf-8") as output:
            output.write('<!doctype html><meta charset="utf-8">'
                '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; img-src data:">'
                '<title>Private ABA Sandbox QR</title><h1>Sandbox test only</h1>'
                '<p>Check the amount in ABA Simulator before confirming.</p>'
                '<img alt="Sandbox QR" src="' + html.escape(image, quote=True) + '">')
        return {"outcome": "QR_READY", **ids, "qr_file": str(qr_file)}, 0


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("create", "worker-once", "verify"))
    parser.add_argument("--authorize-live-sandbox", action="store_true")
    parser.add_argument("--customer-id", type=int)
    parser.add_argument("--payload")
    parser.add_argument("--receipt")
    parser.add_argument("--payment-id", type=int)
    args = parser.parse_args(argv)
    if not args.authorize_live_sandbox:
        print('{"outcome":"EXPLICIT_AUTHORIZATION_REQUIRED"}')
        return 2
    if args.action == "create" and not (args.customer_id and args.payload and args.receipt):
        parser.error("create requires --customer-id, --payload and --receipt")
    if args.action == "verify" and not args.payment_id:
        parser.error("verify requires --payment-id")
    try:
        from app import create_app
        app = create_app()
        prepare_config(app)
        with app.app_context():
            if args.action == "create":
                payload = json.loads(Path(args.payload).read_text(encoding="utf-8-sig"))
                result, code = create_probe(args.customer_id, payload, args.receipt)
            elif args.action == "worker-once":
                # Existing advisory lock, leases, scheduling and Telegram retries.
                PaymentWorker(app).tick()
                result, code = {"outcome": "WORKER_TICK_RETURNED_CHECK_DATABASE"}, 0
            else:
                PaymentService().verify(args.payment_id)
                result, code = {"outcome": "CHECK_RETURNED_CHECK_DATABASE"}, 0
        print(json.dumps(result))
        return code
    except Exception:
        # Never render exception text, SQL parameters, customer data or gateway bodies.
        print('{"outcome":"STOPPED_INSPECT_RECEIPT_AND_DATABASE_DO_NOT_REPEAT_CREATE"}')
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
