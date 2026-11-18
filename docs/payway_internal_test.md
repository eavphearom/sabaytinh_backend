# Controlled internal Sandbox payment test

## Internal QR signature correction

The internal checkout initially signed a SQLAlchemy Currency enum as
`Currency.USD`, while JSON transmitted `USD`. The standalone probe used a plain
string, so it did not expose this mismatch. The client now normalizes currency
to its enum value before signing and serialization. Offline tests reconstruct
the expected HMAC from the transmitted JSON, with and without a callback URL.
This fixes a demonstrated signing defect; it does not prove a previously rejected
request created no gateway transaction or guarantee that all merchant restrictions
are satisfied.

For an existing INITIALIZATION_UNRESOLVED order, retain its receipt, payment ID,
transaction ID and reserved stock. Do not rerun create, reset transaction_id or
retry initialization. After explicit authorization use the targeted `verify`
command below with that payment ID. PENDING preserves the reservation; APPROVED
must pass all existing evidence checks before settlement. Not-found, errors or
contradictions require manual review, not automatic cancellation or a new attempt.
If a pending transaction exists but no QR was retained, do not reinitialize it;
resolve it through supported gateway recovery/merchant support first. A separate
new test requires explicit authorization after this attempt is safely resolved.

Prepared commands only: do not execute until the operator authorizes live Sandbox
requests and one real local order/stock reservation. No public endpoint is enabled.
Run from the backend directory using its virtual environment and `.env`.

## Existing acknowledged Close

ABA's [Close specification](https://developer.payway.com.kh/close-transaction-14530822e0)
says closed transactions reject/reverse incoming payments and send no callback.
Its success response is status.code `00` and matching tran_id. The
[Check specification](https://developer.payway.com.kh/check-transaction-14530826e0)
does not promise a post-Close CANCELLED status or document its propagation delay.
Therefore Close 00 followed by PENDING is not evidence of a final CANCELLED state.
Retain the old ID, original amount/currency, timestamp and sanitized diagnostics in
your private manual-review record. Do not repeat Close or pay that old QR. Inspect
the Sandbox portal; seek ABA clarification if unresolved. Check supports only
transactions within seven days; older records need portal/support investigation.
Do not use the close-only diagnostic on a DB-managed order.

## Preparation

Use a dedicated development Sandbox database with the existing migrations applied.
Choose an existing active customer, active USD delivery method and an active product
variant stock with sufficient quantity. Record stock quantity before starting.
CheckoutService validates these again under its normal stock locks. The total uses
real product prices and delivery fees; it is NOT forced to USD 0.01. Inspect the
selected prices first. Do not reuse the old standalone transaction ID.

Keep PAYWAY_PUBLIC_API_ENABLED, PAYWAY_SANDBOX_VERIFIED, PAYWAY_WORKER_VERIFIED and
PAYWAY_CALLBACK_APPROVED false. Credentials must target Sandbox. Callback URL and
secret can remain empty. The CLI enables PAYWAY_SANDBOX_ENABLED in its own process
only; it does not edit `.env` or readiness attestations. No web server is started.

Create a private directory outside the repository:

```powershell
$probeDir = Join-Path $env:LOCALAPPDATA 'GoShoesSandboxTest'
New-Item -ItemType Directory -Force -Path $probeDir | Out-Null
notepad (Join-Path $probeDir 'checkout.json')
```

Save the following JSON, replacing IDs with reviewed existing records and recipient
details with your own test information. Do not supply totals:

```json
{
  "delivery_method_id": 1,
  "recipient_name": "Sandbox Test",
  "recipient_phone": "012345678",
  "delivery_address": "Local Sandbox test only",
  "note": "Controlled internal Sandbox test",
  "payment_method": "ONLINE",
  "items": [{"variant_stock_id": 1, "quantity": 1}]
}
```

## Explicitly authorized execution

Replace CUSTOMER_ID with the chosen numeric ID. This is a trusted local operator
command, not an HTTP identity override. It uses the normal internal services.

```powershell
.\.venv\Scripts\python.exe -B -m app.payway_internal_test create `
  --customer-id CUSTOMER_ID `
  --payload (Join-Path $probeDir 'checkout.json') `
  --receipt (Join-Path $probeDir 'run-001.jsonl') `
  --authorize-live-sandbox
```

The receipt is exclusively created and flushed before checkout. Committed order,
payment and invoice IDs are journaled before gateway initialization. Reusing the
same receipt fails before another checkout. This is NOT distributed idempotency:
never delete/change the receipt to retry. If the process dies before committed IDs
are written, inspect recent orders for that customer before taking any action.
If initialization times out, preserve the order and stock reservation and let the
worker verify the stored transaction ID. Never create a replacement QR/order.
No automatic Close/cancellation occurs in this harness.

On QR_READY open the returned private HTML file:

```powershell
Start-Process (Join-Path $probeDir 'run-001.qr.html')
```

Use the ABA Simulator supplied through your Sandbox onboarding/portal, scan this
new QR, check the amount/currency and choose successful payment. Do not use a real
banking app. The publicly available API references do not establish current
Simulator installation or button names; use ABA's supplied instructions rather
than an unofficial download. If no Simulator is available, stop and obtain access.
Do not publish QR files, receipt/customer data or credentials. QR lifetime defaults
to 15 minutes; expiry does not prove cancellation or release stock.

## Independent verification and retries

This runs the EXISTING worker, including its advisory lock, per-payment leases,
due scheduling and Telegram retry job. It processes ALL due payments/notifications
in this database, not just this order. Review the queue first; do not use a shared
production database. The authorization flag covers those gateway/Telegram calls.

```powershell
.\.venv\Scripts\python.exe -B -m app.payway_internal_test worker-once --authorize-live-sandbox
```

Repeat after next_check_at is due; each invocation is a fresh worker process, so
this also exercises restart recovery. A completed tick is not proof of PAID: a
competing worker, lease, retry delay or error can defer work. Inspect DB state.
For an explicitly authorized duplicate check of this payment only, replace ID:

```powershell
.\.venv\Scripts\python.exe -B -m app.payway_internal_test verify --payment-id PAYMENT_ID --authorize-live-sandbox
```

Repeat that command after PAID and confirm timestamps/reference, stock and movement
counts remain unchanged. Existing service idempotency may short-circuit gateway I/O
for paid records. Do not alter scheduling fields or payment states manually.

## PostgreSQL evidence (read-only)

Replace 123 with the receipt's payment ID. Do not query QR, leases or credentials.

```sql
SELECT p.id AS payment_id, p.transaction_id, p.amount, p.currency,
       p.payment_status, p.paid_at, (p.payment_reference IS NOT NULL
       AND p.payment_reference <> '') AS has_approval_reference,
       p.gateway_state, p.next_check_at,
       o.id AS order_id, o.order_code, o.total_amount, o.currency AS order_currency,
       o.payment_status AS order_payment_status, o.order_status,
       i.payment_status AS invoice_payment_status, i.paid_at AS invoice_paid_at
FROM payments p JOIN orders o ON o.id = p.order_id
JOIN invoices i ON i.order_id = o.id AND NOT i.is_deleted
WHERE p.id = 123 AND NOT p.is_deleted;

SELECT s.variant_stock_id, s.type, s.reference_type, s.qty_before, s.qty_after,
       s.base_qty_change
FROM stock_movements s
WHERE s.reference_id = (SELECT order_id FROM payments WHERE id = 123)
  AND s.reference_type IN ('ORDER', 'ORDER_RETURN') ORDER BY s.id;
```

Success requires Payment, Order.payment_status and Invoice.payment_status all PAID,
paid timestamps and approval reference present, same transaction ID and original
amount/currency, and one initial deduction per purchased stock with no duplicate
deduction. Order fulfillment status need not become DELIVERED. The existing client
checks APPROVED/code 0, matching amounts, currency and approval evidence independently.
Cross-currency approvals are still rejected until supported validation is established.

Verify Telegram actually arrives for event `payment:PAYMENT_ID:paid`, then check its
pending marker clears. Missing Telegram credentials must not prevent PAID settlement.
Existing durable retry markers survive restart, but Telegram has no idempotency key:
a crash after Telegram accepts a message and before local acknowledgment can duplicate
delivery. Do not claim exactly-once external delivery.

## Before React checkout

Retain one real successful APPROVED/PAID run, duplicate-check and worker restart
evidence, stock movement checks and Telegram results. Resolve or explicitly track
the old Close/PENDING discrepancy; do not infer safe cancellation from timeout.
Review uncertain initialization/manual-review recovery and cancellation separately.
Keep stock reserved for unresolved transactions. Keep callbacks disabled without
verified callback configuration; callback-independent checkout needs an operational
separate worker. Only after reviewing that evidence should the operator explicitly
authorize public Sandbox readiness/checkout changes. This does not enable production.
