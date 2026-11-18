## Callback-independent Sandbox flow

Checkout and reconciliation no longer require a callback URL or callback secret. Leave both empty when callback delivery has not been validated. The client already supports omission of the QR callback field; its position in the HMAC field sequence contributes an empty string. Signing and verification algorithms are unchanged.

The public checkout/check/cancel gate still requires PAYWAY_PUBLIC_API_ENABLED, PAYWAY_SANDBOX_VERIFIED, and PAYWAY_WORKER_VERIFIED, plus valid sandbox-only client configuration. Callback requests additionally require PAYWAY_CALLBACK_APPROVED, a nonempty PAYWAY_CALLBACK_SECRET, and a configured/registered HTTPS callback URL. No URL means no callback route is registered. A configured URL alone does not enable callbacks. Treat CALLBACK_APPROVED as an attestation of authentic callback testing, not merely possession of a secret.

This section supersedes any callback-required readiness checklist below for callback-independent testing. No application code toggles these flags.

### Controlled test sequence (manual authorization required; not executed)

1. Keep public flags false and callback URL/secret empty; keep CALLBACK_APPROVED false. Configure real sandbox merchant ID and HMAC API key locally, sandbox host, sandbox enablement, and the existing 15-minute lifetime. Verify migration status and test inventory/account. Do not use production credentials.
2. Obtain explicit authorization for live sandbox requests. First use the existing QR-only smoke procedure to establish QR/check/close protocol compatibility with the merchant account. Do not scan its QR: that probe is for safe initialization/closure, not a completed-payment test.
3. For an actual end-to-end paid test while public APIs remain disabled, use a trusted local Flask shell and the existing internal CheckoutService.checkout(authenticated_user_id, payload), then PaymentService.initialize(result['payment_id']). Use a real test customer and server-priced stock IDs; never fabricate payment evidence. This creates an actual sandbox order and deducts inventory. Record order/payment/transaction IDs. If initialization fails, inspect and reconcile the existing transaction; never initialize a replacement automatically.
4. Run the dedicated worker in a separate terminal: `.venv\Scripts\python.exe -m app.workers.payment_worker`. For a bounded verification cycle use `--once`. Starting it makes live gateway calls for due payments when configured, so start only after authorization and review pending test records first.
5. Scan the successful test QR using the sandbox procedure supported for your merchant account. Observe the worker independently verify approval and persist matching PAID Order/Payment/Invoice evidence. An internal PaymentService.verify(payment_id) is also supported. Repeat checks to confirm no duplicate inventory or financial transitions. Capture sanitized evidence; never record keys or tokens.
6. Test worker shutdown/restart with a pending payment and expired lease. Timeouts/QR expiry must leave stock reserved and payment unresolved. For an unpaid test use PaymentService.cancel(payment_id, customer_id, reason): stock returns only after confirmed Close evidence. Check duplicate cancellation restores stock once. Late approval after cancellation must require refund review, not fulfillment. Pending records older than seven days enter the existing manual-review path.
7. Only after retaining actual QR, approved check, cancellation, and worker recovery evidence should the operator attest SANDBOX_VERIFIED and WORKER_VERIFIED. A separate explicit authorization is required before enabling PUBLIC_API_ENABLED for a limited authenticated frontend test. Keep callbacks disabled throughout. Do not mark live requirements verified based on mocked tests.

Callback independence does not imply exactly-once external notification delivery. Existing durable notification deduplication/retry limitations remain. Worker downtime delays settlement; cancellation uncertainty requires review. A crash between checkout commit and gateway claim can leave a payment without a transaction ID: inspect it manually rather than automatically generating another payment attempt.

---

# PayWay sandbox integration

The sandbox integration is disabled by default. Step 6 adds gated public order
routes; see [Order APIs](order_api.md) for their explicit enablement requirements.
The [Telegram sender](telegram_notifications.md) and separate [background worker](payment_worker.md) are available; no production gateway is enabled. Existing
checkout transactions and inventory standalone APIs are unchanged.

## Protocol references

Verified against the official specifications on November 10, 2026:

- [QR API](https://developer.payway.com.kh/qr-api-14530840e0.md)
- [Check transaction](https://developer.payway.com.kh/check-transaction-14530826e0.md)
- [Close transaction](https://developer.payway.com.kh/close-transaction-14530822e0.md)
- [API access / whitelisting](https://developer.payway.com.kh/api-endpoints-984508m0)

Requests use Base64 HMAC-SHA512 with the documented field order. Request times
are UTC; stored timestamps use the project's local naive timestamp convention.
The check endpoint's prose omits req_time from its hash description, but its
explicit PHP example includes it. This implementation follows that example.
The Spring Boot client was not present for comparison.

PayWay's documented APIs do not supply a response signature or echo merchant ID
in verification responses. Evidence is bound to the configured merchant through
the signed request and TLS-verified response from the fixed sandbox host. The
echoed transaction ID, original/total/paid amounts, currency, approval code, zero
refund amount, and APPROVED status/code must match. PRE-AUTH is not approval.
No response-signature formula is invented. Callback authentication follows the
separately supplied Spring helper, with documented ABA compatibility checks.

Callbacks must first pass [Spring-compatible callback HMAC verification](payway_callback_security.md)
using PAYWAY_CALLBACK_SECRET. Their financial claims remain untrusted:
`callback_hint()` performs a server-to-server check. The configured callback route enforces input limits and
a per-worker rate limit; public deployments also require shared proxy rate
limiting. Browser redirects and client status fields are never evidence.

## Configuration

Use sandbox-only credentials in local environment variables, never source code.
See `.env.example` for PAYWAY_* names. The base URL must be exactly the official
HTTPS sandbox host. The three endpoint paths are fixed to the verified paths.
HTTP redirects are rejected. Connect/read timeouts are separate; the lease must
cover three calls' timeout budgets plus ten seconds. Responses are size-limited.

Merchant ID, API key, and a public HTTPS callback URL must be provided. Confirm
the merchant is a sandbox account and that ABA has whitelisted the applicable
domain/IP and callback URL. The code cannot infer credential provenance.

The caller must configure PAYWAY_SANDBOX_ENABLED=true explicitly. Configuration
is checked before any lease or payment initialization is written.

## Orchestration and transactions

After `CheckoutService.checkout()` commits, call
`PaymentService.initialize(result['payment_id'])`. The gated OrderService public
orchestrator follows this flow. It returns the existing PaymentResponseSchema fields. The QR
image is returned transiently, never stored. The QR API has no checkout QR URL
or expiry timestamp in its documented response: the URL stays null and expiry
is conservatively derived from request start plus requested lifetime.

Each gateway operation has three stages:

1. Lock order -> payment -> invoice, validate consistency, save a transaction ID
   and token/expiry lease, then commit.
2. Perform signed HTTPS operations without a DB transaction or row lock.
3. Re-lock, compare the lease token and expiry, validate evidence, and commit
   financial updates atomically. Stale workers cannot apply a result.

Timeouts, malformed responses, unknown statuses, and hash errors preserve the
existing transaction ID and stock, release the matching lease, and schedule a
check. Retrying initialization does not create a new gateway attempt. Recovery
of an initialization that was never accepted by ABA is intentionally manual;
"transaction not found" is not sufficient evidence to release stock.

## Verification, reconciliation, cancellation

APPROVED evidence updates Payment, Order, and Invoice payment statuses and both
available paid_at fields in one commit. Order has no paid_at column. Repeated
verified checks are idempotent. The order fulfillment status is not advanced.

Schedule `PaymentService.reconcile_due()` separately. Expired QR codes only
trigger verification; they do not imply nonpayment or release stock. The check
API supports transactions created within seven days. Older unresolved payments,
refunds, inconsistent records, and unsupported statuses require manual review;
no undocumented status or detail-API fallback is guessed.

Customer cancellation requires ownership and a PENDING order. It first checks
payment. An approved payment is recorded instead of cancelling. Otherwise it
calls Close Transaction and requires a successful matching confirmation. Only
then are stock returns, cancellation history, and all local cancellation states
committed together. The CANCELLED order state prevents repeated restoration.
Multiple payment attempts are rejected for cancellation until an all-attempt
closure policy exists. A gateway-closed/local-commit failure leaves stock held
and can be retried; it never releases stock based on uncertainty.

Late approved evidence for a CANCELLED order records PAID financial evidence and
REFUND_REVIEW state without reopening the order or deducting stock again.

## After-commit events

Pass `paid_hook(event)` to PaymentService or PaymentStateService. Before the first
PAID commit, gateway_state records PAID_NOTIFY_PENDING or
REFUND_REVIEW_NOTIFY_PENDING. The hook runs after commit with no DB transaction.
Successful delivery clears the marker; failure/crash leaves it retryable after
lease expiry. Use `TelegramNotificationService().retry_pending()` explicitly for
Telegram recovery, or run the dedicated worker for automatic retries.

Delivery is at least once, not exactly once: consumers MUST deduplicate stable
`event_id = payment:<id>:paid`. The event includes refund_review so a late payment
cannot trigger normal fulfillment. These internal gateway_state markers must be
preserved by future features. PaymentService now defaults to the Telegram hook;
see [Telegram delivery limits and recovery](telegram_notifications.md). Telegram
cannot guarantee exactly-once delivery because sendMessage has no idempotency key.

## Validation and remaining enablement work

### Optional internal QR-only probe, without a callback URL

Rechecked the official [QR OpenAPI schema](https://developer.payway.com.kh/qr-api-14530840e0.md):
`callback_url` is a property but is absent from the request `required` list.
The required fields are req_time, merchant_id, tran_id, payment_option, amount,
lifetime, qr_image_template and hash, plus currency. Its position remains in
the signing field list; the omitted value contributes an empty string, not
`null`, a fake URL, or a delimiter. This corrects the earlier conclusion based
on Flask's stricter application-level configuration validator.

Only the internal probe constructs `PayWayClient(..., require_callback=False)`.
It uses a copy of configuration, omits callback_url entirely, and reuses the
existing QR validation and bounded Check/Close cleanup. It creates a 0.01 USD
sandbox transaction without paying it, exposing a QR, or writing order records.
The normal client, checkout gate, callback HMAC validation and worker keep their
existing callback requirements. The probe does not set readiness flags.

The schema establishes optionality, but does not guarantee merchant access or
specify whether an account-configured callback might be used when omitted.
Do not infer that callbacks are globally disabled at ABA. No public Flask route
is enabled by this test. Merchant/IP whitelisting and real sandbox acceptance
remain unverified until an explicitly authorized live run.

For an **explicitly authorized live** run, from the backend directory:

```powershell
.\.venv\Scripts\python.exe -B -c "import os, unittest; os.environ['PAYWAY_SANDBOX_ENABLED']='true'; os.environ['PAYWAY_RUN_QR_ONLY_TESTS']='true'; unittest.main(module='tests.test_payway_sandbox_qr_only', verbosity=2)"
```

The command opts into the sandbox only inside its child Python process; it does
not edit `.env` or change the parent shell, public API or readiness flags.
PAYWAY_MERCHANT_ID and PAYWAY_API_KEY must already contain sandbox credentials;
PAYWAY_BASE_URL must remain the official sandbox host. Callback URL/secret may
remain empty. Capture stderr transaction IDs and investigate any UNRESOLVED or
PAID_MANUAL_REVIEW result. Do not scan/pay the generated transaction. Success
proves QR generation, a pending check and confirmed closure—not paid verification
or callback readiness. Offline tests: `python -m unittest tests.test_payway_qr_only`.

### Existing regression and callback-configured smoke tests

- Run `python -m unittest tests.test_payway_client` for mocked protocol tests.
- Set CHECKOUT_TEST_DATABASE_URL for PostgreSQL financial/concurrency tests in
  a generated disposable schema; no public tables or migrations are changed.
- PAYWAY_RUN_SANDBOX_TESTS=true explicitly opts into
  `python -m unittest tests.test_payway_sandbox`. This additionally requires all
  sandbox settings. It initializes, checks, and closes a 0.01 USD sandbox-only
  transaction, without making a customer payment.
- The smoke test prints its generated transaction ID to stderr before QR
  initialization. Capture that output for recovery. Initialization timeout or
  malformed QR response still triggers verification using the same ID; it never
  assumes the transaction is absent or initializes a replacement. Verified
  PENDING/CANCELLED/DECLINED results permit a closure attempt. APPROVED requires
  manual review and is never closed/refunded by the test. Failed verification
  leaves the transaction unresolved without attempting closure blindly.
- Closure is confirmed only by the client's validated CLOSED evidence. If
  closure fails/times out, one further check looks for a racing payment; even a
  CANCELLED check result does not substitute for closure confirmation. Unresolved
  IDs are reported for manual follow-up. QR failure still fails the test even
  when cleanup succeeds. No retries create a new transaction. A hard process
  termination cannot guarantee cleanup; use the previously printed ID.
- Offline recovery checks: `python -m unittest tests.test_payway_sandbox_cleanup`.
- Run the real sandbox smoke test after credentials/whitelisting are ready.
  Mocks do not prove merchant enablement or live gateway behavior.
- Before enabling the public APIs: configure shared rate limiting and the
  readiness flags documented in order_api.md and verify the separate worker. Pending-init
  recovery, refund-review handling, and a deduplicating notification consumer
  remain separate operational work.


## Diagnosing UNRESOLVED_VERIFICATION without creating another transaction

The exact assertion `Cleanup requires manual follow-up; ... cleanup=UNRESOLVED_VERIFICATION` means initialize returned matching READY evidence, then the first cleanup check failed or returned unsupported/mismatched evidence. Close was not attempted. If initialization failed, the assertion instead begins `QR initialization failed or unconfirmed`. No original exception is retained by the old smoke test, so this message cannot identify the underlying HTTP/protocol/transport error retrospectively.

PayWayClient now emits allowlisted diagnostic lines with operation, HTTP status, numeric gateway code, known field types, and a fixed validation-failure reason. No bodies, hashes, keys, QR contents, customer fields, approval values, or exception text are logged. The smoke test separately reports READY_CONFIRMED or FAILED_OR_UNCONFIRMED. A status code of 200 does not establish a successful gateway operation; inspect gateway_code and validation_failure too.

No protocol validation was relaxed. The documented Check example has status.code="00", matching status.tran_id and a data object with original_amount, total_amount, payment_currency and coherent payment_status/payment_status_code. The actual pending response remains unobserved locally. Missing fields or different types require captured safe diagnostics and confirmation against the applicable ABA specification, not guessed defaults.

### Previously unresolved IDs: verification-only manual procedure

Do not rerun either smoke test to investigate an old ID: both create a fresh transaction. Do not scan old QR codes, initialize replacement attempts, auto-refund, or mark records closed because QR time expired.

After explicit authorization for a live read, use a trusted local Flask shell with the same Sandbox merchant credentials and the exact original transaction ID. For this project's QR-only probe the original amount is USD 0.01. Construct PaymentContext(0, 0, original_transaction_id, configured_merchant_id, Decimal("0.01"), "USD", "manual-review"), then call PayWayClient(config, require_callback=False).verify(context) only. Record the safe diagnostic lines and resulting status; never print the config or raw gateway response. This performs no QR generation or local database settlement.

If verification is APPROVED, stop and review the paid transaction; do not close it. If verification fails, keep it unresolved and inspect the merchant Sandbox transaction portal or request ABA investigation with transaction ID and sanitized evidence. If valid nonpaid evidence is returned, closure is a separate authorized operation using the same context, followed by inspection of confirmed Close evidence. A failed Close response stays unresolved. Never substitute another merchant, amount, currency or transaction ID to make validation pass.

The official Check Transaction API only covers transactions created within seven days. For older IDs, use the merchant portal or the official Get a transaction details workflow after reviewing that endpoint's protocol; this client does not implement it. No automatic fallback or new transaction is appropriate.

References:
- https://developer.payway.com.kh/check-transaction-14530826e0
- https://developer.payway.com.kh/close-transaction-14530822e0


### Standalone verification-only diagnostic

From the backend directory, explicitly run (replace all original-context placeholders):

```powershell
.\.venv\Scripts\python.exe -B -m app.payway_verify_only --transaction-id "ORIGINAL_TRANSACTION_ID" --merchant-id "ORIGINAL_MERCHANT_ID" --amount "ORIGINAL_AMOUNT" --currency "USD" --allow-live-check
```

For the existing QR-only smoke tests the original amount is `0.01` USD. Do not assume this for other transactions. The merchant ID must match local PAYWAY_MERCHANT_ID; the API key is read locally and must belong to that merchant. No key or signature belongs in command arguments. Without --allow-live-check no network request occurs. The command refuses initialization/closure and calls only Check, once, without retries or database writes. Existing sandbox configuration must already be valid; it never sets readiness flags.

Output is limited to http_status, gateway_status_code, response_data_type, response_field_types and validation_failure_reason. Null validation_failure_reason with exit 0 means response validation passed, not necessarily PAID: payment state values are deliberately not displayed. Exit 1 means gateway/validation failure; exit 2 means local input/configuration or opt-in failure. HTTP 200 alone is not payment evidence. If HTTP status is null, no response status was captured; this does not prove that the gateway received no request. Missing/type-mismatched fields identify where protocol investigation is needed; do not remove verification checks to get a passing result. Keep original IDs unresolved until verified gateway evidence establishes their actual state.


### Diagnostic process-local Sandbox opt-in

If local PAYWAY_SANDBOX_ENABLED is false, verification previously failed before HTTP with a generic reason. It now reports `sandbox_disabled`. Use `--enable-sandbox-for-check` to enable Sandbox in a private diagnostic configuration copy only. This does not change .env, Config, the worker, or any public/callback/readiness flag. It does not itself authorize HTTP: `--allow-live-check` is still required.

Safe preflight (no HTTP):
```powershell
.\.venv\Scripts\python.exe -B -m app.payway_verify_only --transaction-id "ORIGINAL_TRANSACTION_ID" --merchant-id "ORIGINAL_MERCHANT_ID" --amount "0.01" --currency "USD" --enable-sandbox-for-check --check-config
```
For an explicitly authorized single live Check request, replace `--check-config` with `--allow-live-check`. Use 0.01 USD only for the original QR-only probe; otherwise supply the exact original amount. `--check-config` always prevents HTTP even if both flags are present. A successful preflight has null HTTP status and null failure reason; that is not gateway evidence.

The diagnostic explicitly loads backend/.env without overriding existing process environment variables. Numeric parse failures identify only the configuration key; configuration validation reasons distinguish sandbox_disabled, invalid_sandbox_host, invalid_merchant_configuration, api_key_missing, invalid_callback_url, invalid_gateway_timeouts, invalid_gateway_lease, and invalid_qr_lifetime. Values and exception text are never printed. Configuration errors exit 2; gateway/transport validation failures exit 1.


### PENDING currency handling and safe status diagnostics

Check verification now validates the status/code pair before applying currency rules. Exactly PENDING with integer code 2 permits absent or empty-string payment_currency; explicit null, malformed currency, and nonempty mismatches remain rejected. original_amount and total_amount must still match the stored amount. original_currency is not required by the published Check example; if supplied it must match. APPROVED still requires all existing approval, payment amount, zero-refund and currency checks. Cross-currency settlement remains unsupported pending a confirmed conversion-verification contract.

The verification-only JSON now includes allowlisted payment_status and payment_status_code. These are gateway claims until all validation succeeds; an HTTP/gateway success alone is not payment approval. Re-run the existing verification-only command only when you explicitly intend a live Check. No new live check was performed to implement this change. Earlier documentation that says payment status values are omitted is superseded by this paragraph.


### Explicit cleanup of an existing QR-only probe

The original probe's Close client validates gateway code 00 and the matching transaction ID. Its internal CLOSED result indicates Close API success, not a second Check response. The new standalone diagnostic keeps these separate and adds one final Check:

```powershell
.\.venv\Scripts\python.exe -B -m app.payway_close_only --transaction-id "ORIGINAL_TRANSACTION_ID" --merchant-id "ORIGINAL_MERCHANT_ID" --amount "0.01" --currency "USD" --enable-sandbox-for-close --allow-live-close
```

Run only for the original USD 0.01 standalone probe after explicitly authorizing live closure. It never generates QR, opens a database session, changes readiness flags, or retries Close. The process-local Sandbox switch changes only a copied client configuration. It validates the original context, immediately checks status, closes only for validated PENDING/DECLINED/CANCELLED, and checks once afterward. APPROVED or failed verification prevents Close. A payment can race the requests; final APPROVED requires manual review rather than an automatic refund.

- close_api_confirmed: valid matching successful Close API response received.
- final_status: validated subsequent Check status, or null when validation failed.
- final_cancelled_confirmed: true only when Close succeeded AND subsequent Check validated CANCELLED.
- Exit 0: both forms of evidence received. Exit 1: unresolved outcome or paid review required. Exit 2: no live authorization or invalid configuration/context.

Final PENDING or missing/invalid currency evidence stays unresolved even after accepted Close. Do not weaken Check validation or infer final cancellation from QR expiration. A lost Close response plus CANCELLED is also not treated as confirmed Close evidence. Follow up through verification-only checks or the merchant portal, not by generating replacement transactions.

This tool is for standalone probe cleanup, not application-order cancellation: it deliberately does not update local orders or restore inventory. Use the existing application cancellation service for DB-managed orders.

A successful cleanup is not evidence of a successful paid checkout. Still needed: separately authorized fresh sandbox order, successful QR initialization, actual sandbox payment, independent APPROVED verification and matching PAID database records, idempotent checks, worker recovery, and any intended Telegram delivery verification. Public readiness remains unverified until actual evidence is retained.
