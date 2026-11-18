"""Request-local limits; never mutate configuration shared by web requests."""
from contextlib import contextmanager
from contextvars import ContextVar
from time import monotonic

from sqlalchemy import event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session


active_execution = ContextVar("payment_worker_execution", default=None)


class WorkerStopped(RuntimeError):
    REASONS = {
        "Worker time budget exhausted": "time_budget_exhausted",
        "Worker external request budget insufficient": "insufficient_io_budget",
        "Worker coordinator lost": "coordinator_lost",
        "Worker lock lost": "coordinator_lock_lost",
        "Worker lock acquisition failed": "coordinator_acquisition_failed",
        "Worker unlock failed": "coordinator_release_failed",
        "Worker coordinator release failed": "coordinator_release_failed",
    }

    def __init__(self, message):
        super().__init__(message)
        self.reason = self.REASONS.get(message, "worker_stopped")


class ExecutionScope:
    def __init__(self, seconds=None, connect_timeout=1, read_timeout=2):
        self.started_at = monotonic()
        self.deadline = self.started_at + seconds if seconds is not None else None
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.coordinator_guard = None
        self.issues = set()
        self.stage = "starting"
        self.coordination_checks = 0
        self.payment_results = {}
        self.notifications_delivered = 0

    def check(self, reserve=0, *, coordination=True):
        if self.deadline is not None and monotonic() + reserve >= self.deadline:
            self.issues.add("time_budget")
            raise WorkerStopped("Worker external request budget insufficient" if reserve else "Worker time budget exhausted")
        if coordination and self.coordinator_guard:
            self.coordination_checks += 1
            self.coordinator_guard()
            self.check(reserve, coordination=False)

    def diagnostics(self):
        now = monotonic()
        return {"stage": self.stage, "elapsed_ms": int((now - self.started_at) * 1000),
                "remaining_ms": max(0, int((self.deadline - now) * 1000)) if self.deadline else None,
                "coordination_checks": self.coordination_checks}


@contextmanager
def execution_scope(scope):
    token = active_execution.set(scope)
    try:
        yield scope
    finally:
        active_execution.reset(token)


def checkpoint():
    scope = active_execution.get()
    if scope:
        scope.check()


def set_stage(stage):
    scope = active_execution.get()
    if scope:
        scope.stage = stage


def external_timeouts(connect, read):
    scope = active_execution.get()
    if scope:
        if scope.deadline is not None:
            connect, read = min(connect, scope.connect_timeout), min(read, scope.read_timeout)
        # Connect + write + headers + body, plus time to persist evidence.
        scope.check(reserve=connect + 3 * read + 2 if scope.deadline else 0)
    return connect, read


def read_response(response, connection, limit, timeout):
    scope = active_execution.get()
    if not scope or scope.deadline is None:
        return response.read(limit)
    chunks, size = [], 0
    while size < limit:
        scope.check(coordination=False)
        if connection.sock is not None:
            connection.sock.settimeout(min(timeout, max(0.1, scope.deadline - monotonic())))
        chunk = response.read1(min(16384, limit - size))
        if not chunk:
            break
        chunks.append(chunk)
        size += len(chunk)
    return b"".join(chunks)


@event.listens_for(Session, "after_begin")
def bounded_database_statements(session, transaction, connection):
    scope = active_execution.get()
    if scope and scope.deadline is not None and connection.dialect.name == "postgresql":
        milliseconds = max(100, min(2000, int((scope.deadline - monotonic()) * 1000)))
        connection.execute(text("SELECT set_config('statement_timeout', :timeout, true), "
                                "set_config('lock_timeout', '1000', true)"), {"timeout": str(milliseconds)})


@event.listens_for(Engine, "before_cursor_execute")
def check_before_worker_query(connection, cursor, statement, parameters, context, executemany):
    scope = active_execution.get()
    # The dedicated AUTOCOMMIT coordinator must not recursively check itself.
    if (scope and scope.deadline is not None
            and connection.get_execution_options().get("isolation_level") != "AUTOCOMMIT"):
        # Check the deadline for every query without another remote SQL round
        # trip per statement. Lock ownership is still checked at operation,
        # gateway and commit boundaries through checkpoint().
        scope.check(coordination=False)
