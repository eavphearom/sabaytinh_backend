"""Run with python -m app.workers.payment_worker (separate from the web server)."""
import argparse
import logging
import signal
from threading import Event

from sqlalchemy import text

from app.extensions import db
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
            with db.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as coordinator:
                acquired = coordinator.scalar(text("SELECT pg_try_advisory_lock(:namespace, :id)"),
                    {"namespace": LOCK_NAMESPACE, "id": LOCK_ID})
                if not acquired:
                    return {"leader": False}
                try:
                    results = {"leader": True}
                    jobs = (("payments", self._payments), ("telegram", self._telegram))
                    for name, job in jobs:
                        if self.stop.is_set():
                            break
                        # A broken coordination connection must not silently
                        # reconnect and continue without owning the lock.
                        coordinator.scalar(text("SELECT 1"))
                        try:
                            results[name] = job()
                            logger.info("Payment worker job=%s completed", name)
                        except Exception:
                            # Never log exception text/tracebacks: they may
                            # contain provider URLs, credentials or SQL values.
                            logger.error("Payment worker job=%s deferred; inspect configuration and review queue", name)
                            results[name] = "deferred"
                        finally:
                            db.session.remove()
                    return results
                finally:
                    try:
                        coordinator.scalar(text("SELECT pg_advisory_unlock(:namespace, :id)"),
                            {"namespace": LOCK_NAMESPACE, "id": LOCK_ID})
                    except Exception:
                        coordinator.invalidate()  # Never pool a session holding this lock.

    def _payments(self):
        # Missing credentials must not claim or reschedule financial records.
        try:
            PayWayClient(self.app.config).ensure_configured()
        except (GatewayError, ValueError):
            logger.warning("Payment reconciliation disabled or sandbox configuration incomplete")
            return "not_configured"
        return PaymentService().reconcile_due(limit=self.batch_size, should_stop=self.stop.is_set)

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
