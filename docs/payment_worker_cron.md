# Payment worker on Vercel through cron-job.org

## Implementation and limits

`POST /api/v1/internal/payment-worker/run` authenticates a bearer `CRON_SECRET`
before database access. Use a randomly generated token, 32–256 characters.
This is not a JWT or the cron-job.org REST API key. Missing/weak configured secrets
fail closed. Neither the token nor raw exception/provider/payment data is returned.
GET returns 405. The endpoint has no request parameters or payload controls.

Each request synchronously calls `PaymentWorker.tick()` once. It defaults to one
due payment check and one due notification event, with a 20-second cooperative
budget. It does not start a loop, thread, QR initialization, or checkout. Existing
CLI worker behavior and the public payment readiness gate remain available.

HTTP invocations suppress immediate notification dispatch during settlement:
the committed durable marker is handled by the same tick's Telegram job or a later
retry. No financial transition is changed. Remaining backlog, gateway errors,
notification failure, missing configuration, review-required records, and budget
exhaustion return partial/failure, not a misleading successful completion.

| HTTP | JSON status | Meaning |
| --- | --- | --- |
| 200 | completed | Selected bounded batch completed; pending checks may still be unpaid |
| 200 | skipped | Another worker owns the lock; this invocation did no work |
| 401 | unauthorized | Missing/incorrect bearer token |
| 405 | framework error | GET is not supported |
| 503 | unavailable | CRON_SECRET absent/invalid |
| 503 | partial | Some work failed, was unconfigured, needs review, or remains queued |
| 503 | failed | Configuration, coordinator, or unexpected execution failure |

Successful/partial responses contain aggregate counts and fixed operational
codes, never payment details. `outcome=reconciliation_incomplete` distinguishes
unresolved evidence, manual review and backlog from `outcome=operational_failure`
(budget, coordination, database or execution failures). Both remain HTTP 503.
`payments_checked` counts processed records, including failures/manual review;
it does not mean that many payments were approved. Additional counts are
`payments_unresolved`, `payments_manual_review` and `notifications_delivered`.

## Concurrency and time budget

Use Supabase **Session Pooler on port 5432**, or direct PostgreSQL. Port 6543 is
rejected. Do not route this worker through transaction-mode PgBouncer/Supavisor,
including a custom-port proxy configured in transaction mode. Mode cannot be
reliably inferred from every custom hostname/port: verify it in Supabase.

One pinned AUTOCOMMIT coordinator connection owns the existing session advisory
lock across short financial transactions. Ownership is checked before jobs,
gateway I/O, and state operations/commits. SQL statements and response-body
chunks check the deadline locally, without a remote ownership query each time. An
invalidated coordinator is never silently reconnected. Unlock failure invalidates
the connection and reports failure. Acquisition errors also invalidate it. A
separate database connection runs the financial transactions. Keep at least two
available database connections per invocation; do not configure a one-connection
SQLAlchemy pool. Existing per-order locks and fenced gateway leases remain the
financial protection if a connection is lost during an in-flight external request.

Cron request-local caps default to 1 second connect and 2 seconds read/write;
normal checkout's configured timeouts are unchanged. A normal single exchange's
timeout allowance is roughly `1 + 3*2 = 7` seconds (connect, write, headers, body).
Admission reserves 9 seconds including persistence headroom. One payment and one
single-part notification therefore allow about 14 seconds of external I/O,
leaving roughly 6 seconds for database work and overhead. Each additional Telegram
part must pass admission again. Bounded database transactions use a statement
timeout of at most 2 seconds and a lock timeout of 1 second. Database connection
and pool acquisition waits are capped at 3 seconds in application configuration.

This is a **cooperative** limit, not a promise of a strict 20-second wall clock:
DNS, TLS/header processing, coordinator socket stalls, cold starts, proxy queues,
and OS scheduling can exceed estimates. Socket inactivity timeouts are not total
request deadlines. Chunked body reads check the budget; the Vercel 60-second
function duration is the hard execution backstop. cron-job.org may report timeout
at 30 seconds while Vercel finishes or is terminated. Never repeat checkout or
initialize a payment in response to that timeout. The next batch can recover via
persisted IDs, next_check_at and expired gateway leases. A lost server session may
retain its advisory lock until PostgreSQL detects the disconnect; later jobs must
skip rather than defeat that lock.

Vercel Hobby currently supports the selected 60-second ceiling (both Fluid and
legacy maximums). Actual project plan, Fluid settings and generated function
configuration must be checked after deployment; none was accessed from this
workspace. `pyproject.toml` already uses `run:app`; `vercel.json` targets `run.py`.
Verify the deployment shows that function and its 60-second maximum. No Vercel
paid plan or Vercel Cron configuration is introduced.

At the default batch and schedule the theoretical throughput is 12 checks and 12
notification events per hour, shared with repeated checks of still-pending
payments. This is suitable only for low-volume Sandbox testing. Frequent backlog
503s mean the workload exceeds that setting; monitor it, do not hide the failure.
cron-job.org may disable a job after more than 25 successive failures. Enable
failure/disabled notifications. Free hosting is not a delivery SLA and may be
limited by account quotas or provider suspensions.

Historical attempts remain checked within the existing seven-day gateway window.
Old/unresolved evidence still needs manual review. Telegram remains at-least-once:
a crash after send or a partially delivered multi-part event can duplicate parts
on retry. Very large messages that cannot finish within the budget need operator
review; no new per-part persistence was introduced.

## Vercel environment variables

Set these in the **backend** project, not Vite's public frontend variables.

| Variable | Kind | Value / purpose |
| --- | --- | --- |
| CRON_SECRET | New, required | Random private token; identical in Vercel and cron-job.org |
| PAYMENT_CRON_BATCH_SIZE | New, optional | `1`, maximum `2` per job |
| PAYMENT_CRON_BUDGET_SECONDS | New, optional | `20`, allowed 10–25 |
| PAYMENT_CRON_CONNECT_TIMEOUT | New, optional | `1`, maximum 2 seconds |
| PAYMENT_CRON_READ_TIMEOUT | New, optional | `2`, maximum 3 seconds |
| DATABASE_URL | Existing, required | Supabase Session Pooler, `postgresql+psycopg://<user>:<encoded-password>@<session-host>:5432/postgres?sslmode=require` |
| SECRET_KEY | Existing | Keep the application secret |
| JWT_SECRET_KEY | Existing | Keep JWT secret; cron authentication does not use JWT |
| PAYWAY_SANDBOX_ENABLED | Existing | `true` only for the authorized Sandbox environment |
| PAYWAY_BASE_URL | Existing | `https://checkout-sandbox.payway.com.kh` |
| PAYWAY_MERCHANT_ID | Existing, required | Your Sandbox merchant ID |
| PAYWAY_API_KEY | Existing, required | Existing Sandbox HMAC key |
| PAYWAY_CONNECT_TIMEOUT | Existing | `5`; cron caps it locally |
| PAYWAY_READ_TIMEOUT | Existing | `15`; cron caps it locally |
| PAYWAY_LEASE_SECONDS | Existing | `90`; must cover existing client validation |
| PAYWAY_QR_LIFETIME_MINUTES | Existing | `15`; worker does not create QR codes |
| TELEGRAM_BOT_TOKEN | Existing, required | Existing private bot token |
| TELEGRAM_CHAT_ID | Existing, required | Existing destination |
| PAYMENT_WORKER_BATCH_SIZE | Existing CLI setting | `20`; HTTP mode uses separate smaller batch |
| PAYMENT_WORKER_INTERVAL_SECONDS | Existing CLI setting | `15`; not an HTTP scheduler interval |
| PAYWAY_WORKER_VERIFIED | Existing readiness | Keep `false` until deployed worker is validated |
| PAYWAY_PUBLIC_API_ENABLED | Existing readiness | Keep disabled until separately authorized and all checkout conditions pass |
| PAYWAY_SANDBOX_VERIFIED | Existing readiness | Do not change without real Sandbox evidence |
| PAYWAY_CALLBACK_APPROVED | Existing readiness | Keep disabled unless authenticated callbacks are validated |
| PAYWAY_CALLBACK_URL / PAYWAY_CALLBACK_SECRET | Existing, optional | May remain empty for callback-independent reconciliation; never fabricate |

Do not enable live probe environment flags on the deployed app. Keep `.env`
untracked. Rotate CRON_SECRET in both systems if disclosed. The scheduler stores
the bearer credential: restrict access to its account and use HTTPS only.

## ដាក់ឱ្យដំណើរការ ជំហានម្ដងមួយ

1. **Vercel → Backend Project → Settings → Environment Variables**។ បន្ថែម
   `CRON_SECRET` និងពិនិត្យតម្លៃក្នុងតារាងខាងលើ។ កុំដាក់ secret ក្នុង frontend។
   បង្កើត secret ហើយចម្លងទៅ clipboard ដោយមិនបង្ហាញក្នុង terminal៖

   ```powershell
   python -c "import secrets; print(secrets.token_urlsafe(48))" | Set-Clipboard
   ```

   Paste តម្លៃនេះក្នុង Vercel និងរក្សាទុកក្នុង password manager។

2. **Supabase → Connect → Session Pooler**។ ប្រើ connection string port `5432`
   ជាមួយ SSL។ កុំប្រើ Transaction Pooler port `6543`។ កុំប្ដូរ order/payment ដោយដៃ។

3. Push កូដទៅ Git repository ដែល Vercel backend ភ្ជាប់។ បន្ទាប់មកចូល
   **Vercel → Deployments → deployment ថ្មី → Redeploy** បើការប្ដូរ environment
   មិនទាន់បាន deploy។ ពិនិត្យ **Settings → Functions → Function Max Duration**
   និង deployment build details ថា `run.py` មានកំណត់ 60 seconds។ មិនត្រូវ upgrade
   ទៅ paid plan ទេ។ បើ Vercel មិនស្គាល់ function key ត្រូវដោះស្រាយ build configuration
   មុនបើក scheduler; កុំសន្មតថា deployment បានជោគជ័យ។

4. ចម្លង **Production backend domain** ពី Vercel។ ក្នុងឯកសារនេះ
   `<actual-backend-domain>` ជា placeholder ព្រោះមិនបានផ្ទៀងផ្ទាត់ backend domain។
   Frontend domain មិនមែនជា URL សម្រាប់ worker ទេ។ បើ deployment មាន Vercel
   Authentication/Protection ត្រូវរៀបចំការចូលសម្រាប់ scheduler តាម policy របស់អ្នក;
   កុំបិទ authentication របស់ app ឬដាក់ secret ក្នុង URL។

5. សាកល្បង POST ម្ដងតែបន្ទាប់ពីអ្នកអនុញ្ញាត។ វានឹងពិនិត្យ pending payments
   ដែលមានស្រាប់ និងអាចផ្ញើ Telegram ពិត។ វាមិនបង្កើត order/QR ថ្មីទេ។
   ដាក់ secret ក្នុង clipboard ជាមុន ហើយប្រើ៖

   ```powershell
   $workerUrl = 'https://<actual-backend-domain>/api/v1/internal/payment-worker/run'
   $workerToken = (Get-Clipboard -Raw).Trim()
   try {
       Invoke-RestMethod -Method Post -Uri $workerUrl -TimeoutSec 30 `
           -Headers @{ Authorization = "Bearer $workerToken" }
   } finally {
       Remove-Variable workerToken
       Set-Clipboard -Value ''
   }
   ```

   កុំបង្ហាញ token ឬថត screenshot header។ ពិនិត្យ **Vercel → Logs** សម្រាប់
   `Payment cron status=completed`។ 503 មិនមែនជាការជោគជ័យទេ; ពិនិត្យ config,
   backlog, timeout, និង manual-review records។ `skipped` មានន័យថា worker មួយទៀតកំពុងធ្វើការ។

6. បង្កើត Free account នៅ **cron-job.org → Sign up** ហើយ verify email។ ចូល
   **Console → Cronjobs → Create cronjob** រួចកំណត់៖

   - Title: **Sabay Tinh Payment Worker**
   - URL: `https://<actual-backend-domain>/api/v1/internal/payment-worker/run`
   - Execution schedule: **Every 5 minutes** (`*/5 * * * *`)
   - Advanced/request settings → Method: **POST**
   - Headers → Name: `Authorization`; Value: `Bearer <CRON_SECRET>`
   - Request body: ទុកទទេ
   - Timeout: **30 seconds/default Free limit**; មិនត្រូវទិញ membership ដើម្បីបង្កើនទេ
   - Enable failure/disabled email notifications; save sanitized response history if desired
   - ទុក job disabled សិន រហូតដល់ manual test ឆ្លងកាត់

7. ចុច **Test run / Run now** ហើយពិនិត្យ HTTP status និង response។ បន្ទាប់ពី
   test ជោគជ័យ ចុច **Enable / Save**។ រង់ចាំពេល schedule បន្ទាប់ រួចចូល
   **Cronjobs → Sabay Tinh Payment Worker → History** ដើម្បីបញ្ជាក់ថាជា scheduled run
   មែន មិនមែនតែ manual run។ ពិនិត្យ Vercel logs ពេលដូចគ្នា។ UI labels អាចខុសតិចតួច។

8. **GitHub → Actions → ABA Payment Worker**៖ schedule ត្រូវបានដកចេញពី YAML។
   `workflow_dispatch` នៅសល់សម្រាប់ manual rollback ប៉ុណ្ណោះ។ កុំបើក schedule ចាស់
   ឬ long-running CLI worker ជាមួយ cron-job.org ដោយអចេតនា។ Lock អាចការពារការរត់
   ពេលតែមួយ ប៉ុន្តែ duplicate schedulers នៅតែបង្កើនចំនួនការហៅ។

9. ធ្វើ Sandbox payment មួយតាម internal test harness ដែលមានស្រាប់ និងអនុញ្ញាត
   ដាច់ដោយឡែក។ បង់ QR តាម ABA Simulator ហើយរង់ចាំ scheduled worker។ ក្នុង Supabase
   SQL Editor/Table Editor ពិនិត្យ order/payment/invoice ដោយ ID ពី receipt:

   ```sql
   SELECT id, order_status, payment_status FROM orders WHERE id = <order_id>;
   SELECT id, payment_status, paid_at, gateway_state, next_check_at
   FROM payments WHERE order_id = <order_id> ORDER BY id;
   SELECT id, payment_status, paid_at FROM invoices WHERE order_id = <order_id>;
   ```

   Payment, Order payment status និង Invoice ត្រូវបាន PAID ដោយ gateway verification។
   ពិនិត្យថា stock មិនត្រូវបានកាត់ម្ដងទៀត និង Telegram បានផ្ញើម្តងក្នុង normal flow។
   ពិនិត្យ scheduled run បន្ទាប់ថាមិន settle ឬ notify ម្ដងទៀត។ កុំធ្វើ UPDATE SQL ដើម្បី
   បង្ខំ PAID ឬ reset transaction IDs។ សាកល្បង retry ក្នុង Sandbox/test environment
   ដោយអនុញ្ញាតជាមុន ហើយបញ្ជាក់ថា notification failure មិនប៉ះពាល់ financial state។

10. បន្ទាប់ពីបានផ្ទៀងផ្ទាត់ scheduled run ពិត, verified payment settlement និង
    notification/retry behavior រួច ទើបអាចកំណត់ `PAYWAY_WORKER_VERIFIED=true`
    ដោយដៃក្នុង Vercel ហើយ redeploy។ Empty successful batch មួយមិនគ្រប់គ្រាន់ទេ។
    ការបើក public checkout ត្រូវការលក្ខខណ្ឌ Sandbox ផ្សេងទៀត និងការអនុញ្ញាតដាច់ដោយឡែក។

## Verification status and references

### Diagnosing cron HTTP 503

The original `validation_failure=unclassified_failure` is insufficient to prove
an ABA protocol error. The previous decorator also used that label for the local
`WorkerStopped` exception. The worker could then replace a partly completed
batch with `deferred`, losing its count and reporting `checked=0`.

Worker aborts now log `worker_abort=insufficient_io_budget`,
`time_budget_exhausted`, or a specific coordinator reason, with a fixed stage,
elapsed/remaining milliseconds and coordinator-check count. Transport failures
report timeout/transport/JSON categories. Existing HTTP/gateway codes and
amount/currency/transaction validation diagnostics remain intact. No exception
text, secret, QR content or raw response is added to logs.

Removing per-statement/per-body-chunk coordinator round trips reduces remote
database overhead without removing the operation, gateway and commit ownership
checks. Progress already recorded in a batch is preserved on interruption.
Old records outside the seven-day window are routed to review without consuming
the selected batch's gateway-call quota. Candidate scanning remains bounded.
An ambiguous record is deferred without settlement; other eligible records can
continue within the batch limit/budget or in a later invocation.

During investigation a read-only aggregate check found three pending payments,
three RECONCILE_REQUIRED records, two pending due records, one pending record
older than seven days and one pending unscheduled record. These counts are not
proof of the historical invocation's exact failure and may change over time.
No deployed record was modified. Exact deployed cause requires the new logs.

After pushing and redeploying, inspect `outcome`, `reasons` and the matching
`worker_abort`/`transport_failure` log. Do not reset transaction IDs or force
PAID/CANCELLED to clear a 503. No credential, header, routing, readiness or
migration changes are needed for this fix. Local regression run: 286 tests,
284 passed and two live tests skipped, using temporary localhost PostgreSQL
with external HTTPS blocked. The live deployment has not been retested here.

No deployment credentials, linked Vercel project, or verified backend domain were
available in this workspace. No deployment, scheduler creation, readiness change,
real payment call, or Telegram delivery was performed by implementation tests.
No schema migration is required.

Local verification: 280 tests ran, 278 passed, and 2 explicitly live tests were
skipped. PostgreSQL integration tests ran against a temporary localhost-only
PostgreSQL 17 cluster, not the configured Supabase database. External HTTPS was
blocked during tests. The temporary server was stopped and its files removed.
Syntax, Vercel JSON and removal of the GitHub schedule were also checked.

- https://supabase.com/docs/guides/database/connecting-to-postgres
- https://supabase.com/kb/troubleshooting/supavisor-and-connection-terminology-explained-9pr_ZO
- https://vercel.com/docs/functions/configuring-functions/duration
- https://vercel.com/kb/guide/ship-a-flask-app-on-vercel
- https://cron-job.org/en/faq/
- https://docs.cron-job.org/rest-api.html
