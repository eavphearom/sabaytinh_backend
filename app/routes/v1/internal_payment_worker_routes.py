"""Server-to-server trigger. Never return the worker's financial result payloads."""
import hmac
import logging
import math

from flask import Blueprint, current_app, jsonify, request

from app.workers.execution_scope import ExecutionScope, execution_scope, WorkerStopped
from app.workers.payment_worker import PaymentWorker


internal_worker_bp = Blueprint("internal_payment_worker", __name__)
logger = logging.getLogger(__name__)


@internal_worker_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@internal_worker_bp.post("/api/v1/internal/payment-worker/run")
def run_worker():
    secret = current_app.config.get("CRON_SECRET")
    if not isinstance(secret, str) or not 32 <= len(secret) <= 256 or secret != secret.strip():
        return jsonify(status="unavailable"), 503
    header = request.headers.get("Authorization", "")
    scheme, separator, supplied = header.partition(" ")
    if (scheme.lower() != "bearer" or not separator or not supplied
            or len(supplied) > 256
            or not hmac.compare_digest(supplied.encode("utf-8"), secret.encode("utf-8"))):
        return jsonify(status="unauthorized"), 401
    # Authentication precedes all engine access, configuration checks and work.
    try:
        config = current_app.config
        seconds = config.get("PAYMENT_CRON_BUDGET_SECONDS", 20)
        batch = config.get("PAYMENT_CRON_BATCH_SIZE", 1)
        connect = config.get("PAYMENT_CRON_CONNECT_TIMEOUT", 1)
        read = config.get("PAYMENT_CRON_READ_TIMEOUT", 2)
        if (type(batch) is not int or not 1 <= batch <= 2
                or any(type(v) not in (int, float) or not math.isfinite(v) for v in (seconds, connect, read))
                or not 10 <= seconds <= 25 or not 0 < connect <= 2 or not 0 < read <= 3):
            raise ValueError("Invalid cron limits")
        scope = ExecutionScope(seconds, connect, read)
        worker = PaymentWorker(current_app._get_current_object())
        worker.batch_size = batch
        with execution_scope(scope):
            result = worker.tick()
        if result.get("leader") is False:
            logger.info("Payment cron skipped: batch already running")
            return jsonify(status="skipped", reason="already_running"), 200
        payments, telegram = result.get("payments"), result.get("telegram")
        # Only fixed operational codes and aggregate counts leave this endpoint.
        reasons = set(scope.issues)
        unresolved = review = 0
        issues = bool(scope.issues)
        payment_count = len(payments) if isinstance(payments, dict) else 0
        if isinstance(payments, dict):
            unresolved = sum(bool(row.get("verification_pending")) for row in payments.values() if isinstance(row, dict))
            review = sum(bool(row.get("manual_review_required")) for row in payments.values() if isinstance(row, dict))
            if unresolved:
                reasons.add("verification_unresolved")
            if review:
                reasons.add("manual_review_required")
            issues |= any(not isinstance(row, dict) or row.get("verification_pending")
                          or row.get("manual_review_required") for row in payments.values())
        else:
            issues = True
            reasons.add("payments_" + (payments if payments in ("not_configured", "deferred") else "failed"))
        issues |= type(telegram) is not int
        if type(telegram) is not int:
            reasons.add("telegram_" + (telegram if telegram in ("not_configured", "deferred") else "deferred"))
        status = "partial" if issues else "completed"
        operational = reasons - {"verification_unresolved", "manual_review_required", "payment_backlog", "notification_backlog"}
        outcome = "operational_failure" if operational else ("reconciliation_incomplete" if issues else "batch_completed")
        logger.info("Payment cron status=%s checked=%d delivered=%d outcome=%s reasons=%s diagnostics=%s",
                    status, payment_count, telegram if type(telegram) is int else 0, outcome,
                    sorted(reasons), scope.diagnostics())
        return jsonify(status=status, payments_checked=payment_count,
                       outcome=outcome, reasons=sorted(reasons), payments_unresolved=unresolved,
                       payments_manual_review=review,
                       notifications_delivered=telegram if type(telegram) is int else 0), 503 if issues else 200
    except WorkerStopped as exc:
        logger.error("Payment cron operational_failure=%s", exc.reason)
        return jsonify(status="failed", outcome="operational_failure", reason=exc.reason), 503
    except Exception:
        logger.error("Payment cron failed; inspect configuration and worker health")
        return jsonify(status="failed"), 503
