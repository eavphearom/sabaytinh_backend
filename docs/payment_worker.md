# Payment reconciliation and Telegram worker

The application uses a Flask factory and a development `run.py` server. There
was no task queue, scheduler package, or production process-manager configuration.
The new worker is a separate synchronous process with no additional dependency.
Importing Flask or starting web workers does not start background threads.

## Start on Windows

From the backend directory, with the existing virtual environment and `.env`:

```powershell
.\.venv\Scripts\python.exe -m app.workers.payment_worker --once
.\.venv\Scripts\python.exe -m app.workers.payment_worker
```

The first command processes one batch; the second repeats until Ctrl+C.
Run the web server separately. `--once` performs real configured gateway and
Telegram requests: use sandbox credentials only. It is not a dry run or proof
of readiness. Missing credentials skip that job and are logged; the other job
can still run. A zero exit code means the cycle completed, not that every
payment or message succeeded. Top-level cycle failure with `--once` exits 1.

Configuration:

| Environment variable | Default / meaning |
| --- | --- |
| PAYMENT_WORKER_INTERVAL_SECONDS | 15; delay after both batches, integer 1–3600 |
| PAYMENT_WORKER_BATCH_SIZE | 20 per job, integer 1–1000 |
| PAYWAY_WORKER_VERIFIED | false; explicit operator attestation after worker checks |
| PAYWAY_* | Existing sandbox credentials, host, callback URL, timeouts and leases |
| TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID | Required only for Telegram delivery |

SIGINT, SIGTERM and Windows SIGBREAK request graceful shutdown. Payment batches
stop between records; an in-flight call/Telegram batch finishes first. Use small
batches for faster shutdown. A hard stop leaves committed leases to expire.
Socket timeouts are not absolute wall-clock deadlines; supervise stuck processes.

## Production process isolation and coordination

Deploy the same command as a distinct systemd/Supervisor/container service, with
the backend as its working directory and the same database/environment as the
web deployment. Use restart-on-failure, capture stdout/stderr, and configure a
graceful termination period appropriate to batch size/network timeouts. On
Windows use a service wrapper or Task Scheduler with "Do not start a new instance",
the virtual-environment Python executable, `-m app.workers.payment_worker`, and
the backend working directory. Do not use Flask's reloader for the worker.
This deployment guidance does not enable production PayWay: the client remains
restricted to the sandbox host.

Each tick holds PostgreSQL session advisory lock `(1768910437, 8)` on a dedicated
autocommit connection. Other copies skip that tick; the lock releases at its end
or when PostgreSQL detects a dead connection. Use a direct PostgreSQL connection
or session-pooling proxy, **not transaction pooling**, for this session lock.
The coordination connection consumes one pool slot in addition to ORM work.
Failed unlock invalidates the connection rather than returning a locked session
to the pool. Payment row leases still protect financial writes against web
callbacks, manual checks, and coordination-connection loss. No locks/financial
transaction stay open during gateway HTTPS calls. Telegram retains its documented
accepted-but-unacknowledged duplicate window; no exactly-once delivery claim.

Each job's failure is isolated. Logs contain job names/payment IDs, not provider
responses, tokens, recipient details, or tracebacks. Monitor deferred logs,
pending-payment age, and expired leases; a running process alone does not prove
successful reconciliation. PAYWAY_WORKER_VERIFIED is an attestation, not a live
heartbeat. No new persistence or database migration was introduced.

## Reconciliation and recovery

The payment job validates sandbox configuration, then reuses
`PaymentService.reconcile_due()`. It selects nondeleted PENDING ONLINE payments
with due `next_check_at` and no active lease, in due-time order. NULL means
unscheduled. Verification claims the existing fenced gateway lease, validates
gateway evidence and atomically updates financial state only after approval.
An expired operation lease is reclaimable; stale results cannot overwrite a
replacement operation. Pending/transport failures retain stock and schedule
another check. Unexpected record errors do not prevent processing later records;
unprocessable due rows back off five minutes unless the service already scheduled
a retry. No new transaction ID is created on retry.

The official [Check Transaction API](https://developer.payway.com.kh/check-transaction-14530826e0)
only checks transactions created within seven days. Records whose local payment
creation time is at least seven days old are conservatively unscheduled with a
manual-review message (local creation can precede actual gateway initialization).
No transaction-detail fallback or unsupported refund logic is invented.

Timeout, QR expiry, decline/cancel status from a check, and absence of a transaction
are not sufficient evidence for stock restoration under the existing business
rules. The worker never auto-cancels. Use the existing cancellation service/API,
which verifies and obtains definitive gateway closure before the atomic stock
return. Repeated/concurrent cancellation cannot return stock twice. CLOSED
payments are not polled forever; late evidence arrives via a callback hint or
an explicit service verification and is retained as PAID/refund review without
reopening the cancelled order.

Telegram retries reuse `TelegramNotificationService().retry_pending()`, including
its durable pending markers, event ID, active leases, and persisted 429 delays.
They run even when payment credentials are unavailable. Restart recovery uses
database state, not an in-memory queue. See [delivery limitations](telegram_notifications.md).

## Manual review

Use the existing authenticated admin order/payment read APIs and these read-only
queries in the configured schema. Never publish raw payment rows or credentials:

```sql
SELECT id, order_id, payment_status, gateway_state, next_check_at,
       gateway_lease_until, checkout_message, created_at
FROM payments
WHERE is_deleted = false AND payment_method = 'ONLINE'
  AND (payment_status = 'PENDING'
       OR gateway_state IN ('REFUND_REVIEW', 'REFUND_REVIEW_NOTIFY_PENDING',
                            'PAID_NOTIFY_PENDING'))
ORDER BY created_at, id;
```

Investigate NULL schedules, missing transaction IDs, repeated RECONCILE_REQUIRED,
old timestamps, overdue leases, inconsistent order/invoice totals/statuses, and
refund-review markers. Compare against the sandbox merchant portal and official
PayWay support evidence. Fix credentials/connectivity before retrying. For an
existing transaction within the supported window, use
`PaymentService().verify(payment_id)` in an app context; approval must
still pass the same verifier. An uninitialized checkout needs the existing
initialize operation after checking that no gateway attempt exists; never generate
a replacement ID for an uncertain attempt. Outside the supported check window,
contradictions and late approvals require manual investigation; automated refund,
fulfillment, forced PAID updates and inventory release are not recovery steps.

## Sandbox readiness and final Hoppscotch sequence

1. Keep PAYWAY_PUBLIC_API_ENABLED, PAYWAY_CALLBACK_APPROVED,
   PAYWAY_SANDBOX_VERIFIED and PAYWAY_WORKER_VERIFIED false initially.
2. Obtain actual sandbox merchant credentials. Configure the official sandbox
   host, PAYWAY_MERCHANT_ID, PAYWAY_API_KEY, PAYWAY_CALLBACK_SECRET and your own approved HTTPS callback
   URL with a unique path. Confirm domain/IP and callback whitelisting with ABA.
   No credentials or callback URL are supplied by this implementation.
3. Set PAYWAY_SANDBOX_ENABLED=true for internal sandbox testing only. Signing
   remains the existing Base64 HMAC-SHA512 implementation; run client tests and
   confirm real QR generation with the opt-in smoke test described in
   payway_sandbox.md. That smoke test verifies PENDING then closes a transaction;
   it does **not** prove successful paid approval or callback delivery.
4. Use an internal sandbox checkout/initialize session and an authorized sandbox
   payment to prove actual APPROVED verification, correct merchant/transaction,
   amount/currency matching, PAID invoice/order, and no duplicate transitions.
   Never substitute mocked results for this evidence.
5. Start the worker. Observe due payments reconciled, a restart/expired lease
   recovered, and a Telegram retry respecting its delay. Test confirmed closure,
   unchanged stock on timeout/expiry, and one stock return on repeated cancel.
6. Validate callback URL reachability/approval and local callback hint handling
   while the gate is closed (payment callbacks should return unavailable).
   Record successful internal tests and worker operation before operator-setting
   PAYWAY_CALLBACK_APPROVED, PAYWAY_SANDBOX_VERIFIED, PAYWAY_WORKER_VERIFIED=true.
   Only then explicitly enable PAYWAY_PUBLIC_API_ENABLED=true in a controlled
   sandbox environment and restart Flask. No code flips these flags. A real
   end-to-end ABA callback cannot be proven while its route is gated off; this
   is a remaining controlled sandbox acceptance test, not a completed result.
7. In Hoppscotch obtain customer/admin tokens through existing auth APIs, then
   follow docs/order_api.md: checkout, QR initialization/response, complete an
   authorized sandbox payment, verify/check details, confirm callback-triggered
   server verification and worker recovery when a callback is missed. Repeat
   hints/checks and confirm one financial transition. Validate owner isolation,
   paid-only fulfillment, cancellation/stock, and Telegram behavior. Disable
   PAYWAY_PUBLIC_API_ENABLED again if an acceptance check fails.

No real sandbox test or callback delivery was executed as part of Step 8.
Do not enable public payments based solely on passing automated mocks.
