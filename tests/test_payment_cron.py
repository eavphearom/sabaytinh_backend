import unittest
import os
from concurrent.futures import ThreadPoolExecutor
from threading import Event, Lock
from unittest.mock import MagicMock, patch

from flask import Flask

from app.routes.v1.internal_payment_worker_routes import internal_worker_bp
from app.workers.execution_scope import ExecutionScope, WorkerStopped, execution_scope, external_timeouts
from app.workers.payment_worker import PaymentWorker
from tests import test_payment_worker as worker_tests


PATH = "/api/v1/internal/payment-worker/run"
SECRET = "test-only-cron-secret-never-use-in-deployment"


class CronAuthenticationTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, CRON_SECRET=SECRET)
        self.app.register_blueprint(internal_worker_bp)
        self.client = self.app.test_client()
        self.headers = {"Authorization": "Bearer " + SECRET}

    def test_invalid_auth_and_get_never_construct_worker(self):
        with patch("app.routes.v1.internal_payment_worker_routes.PaymentWorker") as worker:
            for header in ("", "Bearer ", "Bearer wrong", "Basic " + SECRET):
                self.assertEqual(self.client.post(PATH, headers={"Authorization": header}).status_code, 401)
            for secret in (None, "", "short", " " * 40):
                self.app.config["CRON_SECRET"] = secret
                self.assertEqual(self.client.post(PATH, headers=self.headers).status_code, 503)
            self.assertEqual(self.client.get(PATH).status_code, 405)
            self.assertEqual(self.client.get(PATH, headers=self.headers).status_code, 405)
            worker.assert_not_called()

    def test_success_contention_failures_and_safe_output(self):
        cases = [({"leader": False}, 200, "skipped"),
                 ({"leader": True, "payments": {}, "telegram": 0}, 200, "completed"),
                 ({"leader": True, "payments": {99: {"verification_pending": True}}, "telegram": 0}, 503, "partial"),
                 ({"leader": True, "payments": {99: {"manual_review_required": True}}, "telegram": 0}, 503, "partial"),
                 ({"leader": True, "payments": "not_configured", "telegram": "not_configured"}, 503, "partial"),
                 ({"leader": True, "payments": "deferred"}, 503, "partial"),
                 ({"leader": True, "payments": {99: {"qr_image": "private", "transaction_id": "private"}}, "telegram": 1}, 200, "completed")]
        for result, status, label in cases:
            with self.subTest(label=label), patch.object(PaymentWorker, "tick", return_value=result) as tick:
                response = self.client.post(PATH, headers=self.headers)
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.json["status"], label)
                self.assertEqual(response.headers["Cache-Control"], "no-store")
                self.assertNotIn("private", response.text)
                self.assertNotIn(SECRET, response.text)
                tick.assert_called_once()
        with patch.object(PaymentWorker, "tick", side_effect=RuntimeError("private credentials")):
            self.assertEqual(self.client.post(PATH, headers=self.headers).json, {"status": "failed"})

    def test_budget_and_notification_deferral_are_not_success(self):
        from app.workers.execution_scope import active_execution
        def partial():
            scope = active_execution.get()
            self.assertIsNotNone(scope.deadline)
            scope.issues.add("telegram_deferred")
            return {"leader": True, "payments": {}, "telegram": 0}
        with patch.object(PaymentWorker, "tick", side_effect=partial):
            self.assertEqual(self.client.post(PATH, headers=self.headers).status_code, 503)
        self.app.config["PAYMENT_CRON_BATCH_SIZE"] = 100
        with patch.object(PaymentWorker, "tick") as tick:
            self.assertEqual(self.client.post(PATH, headers=self.headers).status_code, 503)
            tick.assert_not_called()

    def test_application_factory_registers_endpoint_without_work(self):
        from app import create_app
        with patch.object(PaymentWorker, "tick") as tick:
            app = create_app()
            app.config["CRON_SECRET"] = SECRET
            self.assertEqual(app.test_client().post(PATH).status_code, 401)
            self.assertEqual(app.test_client().get("/api/v1/health").status_code, 200)
            tick.assert_not_called()


class FakeCoordinator:
    def __init__(self, lock):
        self.lock, self.owned = lock, False
        self.closed = self.invalidated = False

    def scalar(self, sql, params=None):
        if self.invalidated:
            raise AssertionError("Must not reconnect after losing coordinator")
        if "pg_try_advisory_lock" in str(sql):
            self.owned = self.lock.acquire(blocking=False)
            return self.owned
        if "pg_advisory_unlock" in str(sql):
            if self.owned:
                self.lock.release()
                self.owned = False
                return True
            return False
        return self.owned

    def invalidate(self):
        if self.owned:
            self.lock.release()
            self.owned = False
        self.invalidated = True

    def execution_options(self, **kwargs):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True


class CronWorkerTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.lock = Lock()
        self.connections = []
        def connect():
            connection = FakeCoordinator(self.lock)
            self.connections.append(connection)
            return connection
        self.db = MagicMock()
        self.db.engine.dialect.name = "postgresql"
        self.db.engine.url.port = 5432
        self.db.engine.connect.side_effect = connect
        self.patcher = patch("app.workers.payment_worker.db", self.db)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def test_concurrent_requests_skip_and_release_lock(self):
        self.app.config["CRON_SECRET"] = SECRET
        self.app.register_blueprint(internal_worker_bp)
        entered, release = Event(), Event()
        def work():
            entered.set()
            self.assertTrue(release.wait(5))
            return {}
        def request():
            return self.app.test_client().post(PATH, headers={"Authorization": "Bearer " + SECRET})
        with patch.object(PaymentWorker, "_payments", side_effect=work), patch.object(PaymentWorker, "_telegram", return_value=0):
            with ThreadPoolExecutor(max_workers=2) as pool:
                first = pool.submit(request)
                try:
                    self.assertTrue(entered.wait(5))
                    self.assertEqual(request().json["status"], "skipped")
                finally:
                    release.set()
                self.assertEqual(first.result().json["status"], "completed")
        self.assertFalse(self.lock.locked())

    def test_coordinator_loss_prevents_next_job(self):
        def lose_connection():
            self.connections[-1].invalidate()
            return {}
        with patch.object(PaymentWorker, "_payments", side_effect=lose_connection), \
             patch.object(PaymentWorker, "_telegram") as telegram:
            with self.assertRaises(WorkerStopped):
                PaymentWorker(self.app).tick()
            telegram.assert_not_called()
        self.assertFalse(self.lock.locked())

    def test_job_exception_releases_and_reports_deferred(self):
        with patch.object(PaymentWorker, "_payments", side_effect=RuntimeError("private")), \
             patch.object(PaymentWorker, "_telegram", return_value=0):
            self.assertEqual(PaymentWorker(self.app).tick()["payments"], "deferred")
        self.assertFalse(self.lock.locked())

    def test_expired_budget_stops_before_work(self):
        with execution_scope(ExecutionScope(-1)), patch.object(PaymentWorker, "_payments") as payments:
            self.assertEqual(PaymentWorker(self.app).tick()["payments"], "deferred")
            payments.assert_not_called()
        self.assertFalse(self.lock.locked())

    def test_transaction_pooler_rejected_before_lock(self):
        self.db.engine.url.port = 6543
        with self.assertRaises(RuntimeError):
            PaymentWorker(self.app).tick()
        self.db.engine.connect.assert_not_called()

    def test_external_caps_are_context_local(self):
        self.assertEqual(external_timeouts(5, 15), (5, 15))
        with execution_scope(ExecutionScope(20)):
            self.assertEqual(external_timeouts(5, 15), (1, 2))
        self.assertEqual(external_timeouts(5, 15), (5, 15))
        with execution_scope(ExecutionScope(1)), self.assertRaises(WorkerStopped):
            external_timeouts(5, 15)

    def test_per_statement_budget_checks_do_not_add_coordinator_round_trips(self):
        from app.workers.execution_scope import check_before_worker_query, checkpoint
        scope = ExecutionScope(20)
        scope.coordinator_guard = MagicMock()
        connection = MagicMock()
        connection.get_execution_options.return_value = {}
        with execution_scope(scope):
            for _ in range(30):
                check_before_worker_query(connection, None, None, None, None, None)
            scope.coordinator_guard.assert_not_called()
            checkpoint()
            scope.coordinator_guard.assert_called_once()

    def test_progress_survives_budget_abort_mid_batch(self):
        from app.workers.execution_scope import active_execution
        scope = ExecutionScope(20)
        def partial():
            active_execution.get().payment_results[123] = {"payment_status": "PENDING"}
            raise WorkerStopped("Worker external request budget insufficient")
        with execution_scope(scope), patch.object(PaymentWorker, "_payments", side_effect=partial):
            result = PaymentWorker(self.app).tick()
        self.assertEqual(len(result["payments"]), 1)
        self.assertIn("insufficient_io_budget", scope.issues)
        self.assertFalse(self.lock.locked())


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "Isolated PostgreSQL URL required")
class CronPostgresTests(unittest.TestCase):
    tearDownClass = classmethod(worker_tests.WorkerPostgresTests.tearDownClass.__func__)
    tearDown = worker_tests.WorkerPostgresTests.tearDown
    payload = worker_tests.WorkerPostgresTests.payload
    payment = worker_tests.WorkerPostgresTests.payment
    due = worker_tests.WorkerPostgresTests.due

    @classmethod
    def setUpClass(cls):
        worker_tests.WorkerPostgresTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(internal_worker_bp)

    def setUp(self):
        worker_tests.WorkerPostgresTests.setUp(self)
        self.app.config.update(CRON_SECRET=SECRET, TELEGRAM_BOT_TOKEN="123:test", TELEGRAM_CHAT_ID="123")

    def trigger(self):
        return self.app.test_client().post(PATH, headers={"Authorization": "Bearer " + SECRET})

    def test_verified_payment_notifies_once_across_http_invocations(self):
        from app.extensions import db
        from app.models import VariantStock, Invoice
        self.gateway.status = "APPROVED"
        with patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7) as send:
            self.assertEqual(self.trigger().status_code, 200)
            self.assertEqual(self.payment().payment_status, "PAID")
            self.assertEqual(db.session.get(Invoice, self.ids["invoice_id"]).payment_status, "PAID")
            self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
            db.session.remove()
            self.assertEqual(self.trigger().status_code, 200)
            send.assert_called_once()

    def test_telegram_failure_is_partial_and_keeps_paid_finances(self):
        self.gateway.status = "APPROVED"
        with patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", side_effect=RuntimeError("private")):
            response = self.trigger()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["status"], "partial")
        self.assertEqual(self.payment().payment_status, "PAID")
        self.assertEqual(self.payment().gateway_state, "PAID_NOTIFY_PENDING")

    def test_gateway_failure_is_partial_and_retains_reservation(self):
        from app.extensions import db
        from app.models import VariantStock
        self.gateway.fail = True
        response = self.trigger()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)

    def test_real_lock_loss_cannot_continue_gateway_work(self):
        from app.extensions import db
        from app.workers.execution_scope import active_execution, checkpoint
        original = self.gateway.verify
        def lose(context):
            # Simulate backend lock loss on the pinned coordinator, not a new session.
            scope = active_execution.get()
            guard = scope.coordinator_guard
            coordinator = dict(zip(guard.__code__.co_freevars,
                                   (cell.cell_contents for cell in guard.__closure__)))["coordinator"]
            coordinator.exec_driver_sql("SELECT pg_advisory_unlock_all()")
            checkpoint()
            return original(context)
        with patch.object(self.gateway, "verify", side_effect=lose):
            self.assertEqual(self.trigger().status_code, 503)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertIsNotNone(self.payment().gateway_lease_token)
        db.session.remove()

    def add_second_due_payment(self):
        from app.extensions import db
        from app.models import Payment
        from app.services.checkout_service import CheckoutService
        from app.services.payments.payment_service import PaymentService
        from app.utils.date_util import DateUtil
        from datetime import timedelta
        ids = CheckoutService().checkout(1, self.payload(quantity=1))
        PaymentService().initialize(ids["payment_id"])
        db.session.get(Payment, ids["payment_id"]).next_check_at = DateUtil.now() - timedelta(seconds=1)
        db.session.commit()
        db.session.remove()
        return ids["payment_id"]

    def test_ambiguous_record_does_not_block_next_payment(self):
        from app.extensions import db
        from app.models import Payment
        from app.services.payments.payment_strategy import GatewayError
        new_id = self.add_second_due_payment()
        self.app.config["PAYMENT_CRON_BATCH_SIZE"] = 2
        def verify(context):
            if context.payment_id == self.payment_id:
                raise GatewayError("Gateway rejected request or returned malformed status")
            return self.gateway.evidence(context, "APPROVED")
        with patch.object(self.gateway, "verify", side_effect=verify), \
             patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7):
            response = self.trigger()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["outcome"], "reconciliation_incomplete")
        self.assertEqual(response.json["payments_checked"], 2)
        self.assertEqual(response.json["payments_unresolved"], 1)
        self.assertEqual(self.payment().payment_status, "PENDING")
        self.assertEqual(db.session.get(Payment, new_id).payment_status, "PAID")

    def test_old_record_does_not_consume_gateway_slot(self):
        from app.extensions import db
        from app.models import Payment
        from app.utils.date_util import DateUtil
        from datetime import timedelta
        new_id = self.add_second_due_payment()
        self.payment().created_at = DateUtil.now() - timedelta(days=8)
        db.session.commit()
        db.session.remove()
        self.app.config["PAYMENT_CRON_BATCH_SIZE"] = 1
        self.gateway.status = "APPROVED"
        with patch.object(self.gateway, "verify", wraps=self.gateway.verify) as verify, \
             patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7):
            response = self.trigger()
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json["payments_manual_review"], 1)
        verify.assert_called_once()
        self.assertEqual(db.session.get(Payment, new_id).payment_status, "PAID")
        self.assertIsNone(self.payment().next_check_at)
        self.assertEqual(self.payment().payment_status, "PENDING")

    def test_batch_one_backoff_allows_next_invocation_to_process_other_payment(self):
        from app.extensions import db
        from app.models import Payment
        from app.services.payments.payment_strategy import GatewayError
        new_id = self.add_second_due_payment()
        self.app.config["PAYMENT_CRON_BATCH_SIZE"] = 1
        def verify(context):
            if context.payment_id == self.payment_id:
                raise GatewayError("Gateway rejected request or returned malformed status")
            return self.gateway.evidence(context, "APPROVED")
        with patch.object(self.gateway, "verify", side_effect=verify), \
             patch("app.services.notifications.telegram_notification_service.TelegramNotificationService._send", return_value=7):
            self.assertEqual(self.trigger().status_code, 503)
            self.assertEqual(self.trigger().status_code, 200)
        self.assertEqual(db.session.get(Payment, new_id).payment_status, "PAID")
