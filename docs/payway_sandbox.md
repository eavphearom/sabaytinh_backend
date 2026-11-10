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
