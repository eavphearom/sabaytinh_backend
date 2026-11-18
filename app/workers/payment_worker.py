"""Run with python -m app.workers.payment_worker (separate from the web server)."""
import argparse
import logging
import signal
from threading import Event

from sqlalchemy import text

from app.extensions import db
from app.workers.execution_scope import ExecutionScope, execution_scope, active_execution, checkpoint, WorkerStopped
from app.services.notifications.telegram_notification_service import TelegramNotificationService
from app.services.payments.payment_service import PaymentService
from app.services.payments.payway_client import PayWayClient
from app.services.payments.payment_strategy import GatewayError


logger = logging.getLogger(__name__)
# Fixed database-scoped advisory lock shared by every instance of this worker.
LOCK_NAMESPACE, LOCK_ID = 1768910437, 8


class PaymentWorker:
    def __init__(self, app, stop=None):
        self.app = app
        self.stop = stop if stop is not None else Event()
        self.interval = app.config.get("PAYMENT_WORKER_INTERVAL_SECONDS", 15)
        self.batch_size = app.config.get("PAYMENT_WORKER_BATCH_SIZE", 20)
        if type(self.interval) is not int or not 1 <= self.interval <= 3600:
            raise ValueError("Invalid payment worker interval")
        if type(self.batch_size) is not int or not 1 <= self.batch_size <= 1000:
            raise ValueError("Invalid payment worker batch size")

    def tick(self):
        """One bounded batch per job; a competing process skips the whole tick."""
        with self.app.app_context():
            if db.engine.dialect.name != "postgresql":
                raise RuntimeError("The payment worker requires PostgreSQL")
            if db.engine.url.port == 6543:
                raise RuntimeError("Session advisory locks require Session Pooler or direct PostgreSQL")
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as coordinator:
                try:
                    acquired = coordinator.scalar(text("SELECT pg_try_advisory_lock(:namespace, :id)"),
                        {"namespace": LOCK_NAMESPACE, "id": LOCK_ID})
                except Exception:
                    coordinator.invalidate()
                    raise WorkerStopped("Worker lock acquisition failed") from None
                if not acquired:
                    return {"leader": False}
                def guard():
                    if coordinator.closed or coordinator.invalidated:
                        raise WorkerStopped("Worker coordinator lost")
                    try:
                        owned = coordinator.scalar(text(
                            "SELECT EXISTS (SELECT 1 FROM pg_locks WHERE locktype='advisory' "
                            "AND pid=pg_backend_pid() AND classid=:namespace AND objid=:id "
                            "AND objsubid=2 AND granted)"),
                            {"namespace": LOCK_NAMESPACE, "id": LOCK_ID})
                        if not owned:
                            raise WorkerStopped("Worker lock lost")
                    except WorkerStopped:
                        coordinator.invalidate()
                        raise
                    except Exception:
                        coordinator.invalidate()
                        raise WorkerStopped("Worker coordinator lost") from None
                scope = active_execution.get() or ExecutionScope()
                scope.coordinator_guard = guard
                try:
                    with execution_scope(scope):
                        results = {"leader": True}
                        jobs = (("payments", self._payments), ("telegram", self._telegram))
                        for name, job in jobs:
                            if self.stop.is_set():
                                results[name] = "deferred"
                                continue
                            try:
                                scope.stage = name
                                checkpoint()
                                results[name] = job()
                                checkpoint()
                                logger.info("Payment worker job=%s finished", name)
                            except WorkerStopped as exc:
                                # Preserve already committed progress even when
                                # the subsequent checkpoint/batch is interrupted.
                                results.setdefault(name, (scope.payment_results or "deferred") if name == "payments"
                                                   else scope.notifications_delivered)
                                scope.issues.add(exc.reason)
                                logger.warning("Payment worker job=%s stopped=%s diagnostics=%s",
                                               name, exc.reason, scope.diagnostics())
                                break
                            except Exception:
                                logger.error("Payment worker job=%s deferred", name)
                                results[name] = "deferred"
                                scope.issues.add("job_failure")
                            finally:
                                db.session.remove()
                        return results
                finally:
                    scope.coordinator_guard = None
                    try:
                        if coordinator.closed or coordinator.invalidated:
                            raise WorkerStopped("Worker coordinator lost")
                        released = coordinator.scalar(text("SELECT pg_advisory_unlock(:namespace, :id)"),
                            {"namespace": LOCK_NAMESPACE, "id": LOCK_ID})
                        if not released:
                            raise WorkerStopped("Worker unlock failed")
                    except Exception:
                        coordinator.invalidate()  # Never pool a session holding this lock.
                        raise WorkerStopped("Worker coordinator release failed") from None

    def _payments(self):
        # Missing credentials must not claim or reschedule financial records.
        try:
            PayWayClient(self.app.config, require_callback=False).ensure_configured()
        except (GatewayError, ValueError):
            logger.warning("Payment reconciliation disabled or sandbox configuration incomplete")
            return "not_configured"
        service = PaymentService()
        scope = active_execution.get()
        if scope and scope.deadline is not None:
            # Settlement retains its durable notification marker. The separate
            # Telegram job owns this invocation's bounded delivery budget.
            service.state.paid_hook = None
        return service.reconcile_due(limit=self.batch_size, should_stop=self.stop.is_set)

    def _telegram(self):
        if not self.app.config.get("TELEGRAM_BOT_TOKEN") or not self.app.config.get("TELEGRAM_CHAT_ID"):
            logger.warning("Telegram retry disabled: credentials missing")
            return "not_configured"
        return TelegramNotificationService().retry_pending(limit=self.batch_size)

    def run(self, once=False):
        logger.info("Payment worker started; no public API flags are changed")
        try:
            while not self.stop.is_set():
                try:
                    self.tick()
                except Exception:
                    logger.error("Payment worker cycle failed; retrying after interval")
                    if once:
                        return 1
                if once:
                    return 0
                self.stop.wait(self.interval)
        finally:
            logger.info("Payment worker stopped")
        return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Run one batch of both jobs, then exit")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from app import create_app
    try:
        app = create_app()
        worker = PaymentWorker(app)
    except Exception:
        logger.error("Payment worker startup failed; check application configuration")
        return 1
    previous = {}
    def request_stop(signum, frame):
        worker.stop.set()
    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            previous[sig] = signal.signal(sig, request_stop)
    try:
        return worker.run(once=args.once)
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


if __name__ == "__main__":
    raise SystemExit(main())
