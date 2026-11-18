# Safe QR renewal

The existing authenticated `POST /api/v1/web/orders/<order_id>/payment/resume`
endpoint needs no request body. Its public readiness gate is unchanged.

- A valid pending QR returns its existing image, transaction ID and expiry.
- An expired QR is verified before any Close request. APPROVED settles through
  the existing verified-payment flow, without replacement.
- Replacement requires both a matching successful Close response and a later
  verified PENDING or CANCELLED Check result without approval conflicts. Close
  success is the non-payability evidence, not the PENDING status itself.
  The persisted acknowledgement prevents
  repeating an acknowledged Close on subsequent resume requests.
- Ordinary DECLINED/CANCELLED, timeouts, code 6, QR expiry and dashboard absence
  alone never authorize replacement. The response remains
  `RECONCILIATION_REQUIRED`, without QR content, while stock remains reserved.

ABA documents that closed transactions reject/reverse incoming payments, but
does not promise that Close success immediately produces CANCELLED in Check.
Renewal relies on that Close guarantee rather than requiring a CANCELLED status.
A failed or contradictory post-close Check still blocks renewal.
It has been tested with mocked evidence, not validated with live ABA renewal.

References:
- https://developer.payway.com.kh/close-transaction-14530822e0
- https://developer.payway.com.kh/check-transaction-14530826e0

## Persistence and concurrency

Migration `d42e9f01a673` follows QR-image migration `b73d1a0e9c42`. It adds nullable
`replaces_payment_id`, `close_accepted_at`, and `closure_verified_at`, a self foreign
key and a unique predecessor constraint. Existing records are not backfilled or
assumed closed. Apply the migration before running the updated web/worker code:

```powershell
.\.venv\Scripts\python.exe -m flask db upgrade d42e9f01a673
```

Review pending migrations before executing; implementation does not apply them.
Do not downgrade after renewals without preserving the lineage/evidence separately.

Order, all payment rows in ID order, and invoice are locked in the same order.
A valid linear chain and order-wide lease exclusion prevent competing attempts.
The predecessor is archived and a new transaction ID/initialization lease are
committed atomically before network I/O. No database transaction spans ABA calls.
One order, invoice, amount and stock reservation are preserved.

If initialization fails or the process crashes after committing the new ID,
reconciliation checks that ID. It never initializes it again or silently creates
another attempt. A crash after Close acknowledgement resumes verification without
repeating Close. Lease expiry allows recovery without accepting stale results.

## Historical approvals and manual review

The worker also checks conclusively closed historical attempts until the existing
seven-day Check window ends. Later records require manual review; the worker does
not use Get Transaction Details automatically. An unexpected historical APPROVED
is retained as PAID evidence with `REFUND_REVIEW`; it blocks customer renewal and
admin fulfillment. It never restores/deducts stock, refunds money, or emits a
second ordinary payment-success notification. Conflicting current approvals are
also flagged. Inspect every payment on the order, not just the newest row.

Normal verified settlement keeps the existing durable notification event and
retry mechanism. Telegram delivery still has its existing at-least-once crash
window; generating a replacement does not send a payment-success notification.

The React resume session already accepts the returned payment ID, uses the
official image in PaymentQrModal, honors the new expiry and polls every four
seconds. No frontend changes or readiness/credential changes are necessary.

No additional migration is required for Close-success/PENDING renewal.
`closure_verified_at` records authorization based on Close plus fresh nonpaid
evidence, not an assertion that ABA returned CANCELLED. The predecessor cancellation reason
retains the post-close Check status; its local CANCELLED status archives the
closed attempt. A provider reversal may not be instant; unexpected late approval
evidence is quarantined for manual review, never automatically refunded.
