# Order APIs

All responses use ApiResponse; financial values are two-place Decimal strings.
Order responses are marked Cache-Control: no-store. No migrations are required.

## Customer endpoints

Use Authorization: Bearer <access_token>. The JWT session, active user, and active
role must be valid. Customer identity always comes from the JWT. Other customers'
orders return 404, including on cancellation and payment checks.

| Method | Path | Behavior |
| --- | --- | --- |
| POST | /api/v1/web/checkout | Gated checkout, then committed-order payment initialization |
| GET | /api/v1/web/orders | Current customer's paginated OrderHistoryResponse rows |
| GET | /api/v1/web/orders/account-overview | Total, in-progress, completed counts |
| GET | /api/v1/web/orders/<id> | OrderResponse details |
| PATCH | /api/v1/web/orders/<id>/cancel | Safe PENDING-order cancellation |
| GET | /api/v1/web/orders/<id>/payment/check | Trusted provider verification, PaymentResponse |

Checkout JSON is the existing CheckoutRequestSchema payload. Cancellation uses
`{"reason": "Changed my mind"}`. A duplicate cancellation returns the current
cancelled order and never repeats stock restoration. Paid or fulfilled orders
require a future refund workflow, not cancellation.

## Admin endpoints

Every endpoint uses the existing admin_required decorator.

| Method | Path | Behavior |
| --- | --- | --- |
| GET | /api/v1/admin/orders | Paginated OrderPaginationResponse rows |
| GET | /api/v1/admin/orders/<id> | OrderResponse details |
| PATCH | /api/v1/admin/orders/<id>/status | Forward-only fulfillment status |
| PATCH | /api/v1/admin/orders/<id>/cancel | Same safe PENDING-only cancellation policy |
| PATCH | /api/v1/admin/orders/<id>/payment-status | Always rejects manual financial changes |
| DELETE | /api/v1/admin/orders/<id> | Soft-delete resolved terminal orders only |

Status body: `{"order_status": "SHIPPED", "note": "Dispatched"}`. PENDING may
skip to SHIPPED or DELIVERED; PROCESSING may skip to DELIVERED. Backward changes
and transitions out of DELIVERED/CANCELLED fail. Identical status requests are
idempotent and do not insert history. CANCELLED must use the cancellation route.
ONLINE fulfillment requires matching PAID order/payment/invoice state plus the
provider-verification markers, approval reference, transaction ID and timestamps.

Admin cancellation retains the customer's ownership association while recording
the authenticated admin as the history/stock-movement actor. It never bypasses
gateway closure or permits cancellation after fulfillment.

DELETE accepts an optional `reason` query parameter (255 characters maximum).
Only DELIVERED with verified payment or CANCELLED with confirmed closure can be
deleted, with no unresolved lease, notification marker, or refund-review state.
Financial verification still works internally after soft deletion, so late paid
evidence is preserved without exposing deleted orders through customer routes.

Pagination parameters: page_no, per_page (1-100), sort_by, sort_dir, search.
Additional filters: order_status, payment_status, customer_id (admin only),
date_from, date_to. Date-only date_to includes that whole day; timestamp date_to
is exclusive. Admin include_deleted=true is supported for lists only. Customer
lists cannot include deleted orders or override the JWT customer with a filter.
total_items counts quantities, not distinct lines. History previews use the
first item by ID; admin lists report the latest payment by creation time/ID.

## Payment enablement and callbacks

Public payment operations require ALL of the following:

- PAYWAY_SANDBOX_ENABLED=true and valid sandbox credentials/timeouts.
- PAYWAY_PUBLIC_API_ENABLED=true (explicit opt-in; defaults false).
- PAYWAY_CALLBACK_APPROVED=true after ABA callback/domain/IP approval.
- PAYWAY_SANDBOX_VERIFIED=true after actual sandbox initialization, verification,
  and closure have been tested successfully. Mock tests do not qualify.
- PAYWAY_WORKER_VERIFIED=true after observing reconciliation and retry/restart recovery.
- PAYWAY_CALLBACK_URL configured with its HTTPS host and a unique literal path.
  Restart the app after changing this URL; the registered path must match it.
- PAYWAY_CALLBACK_SECRET configured; incoming callbacks require a valid
  X-PayWay-HMAC-SHA512 header. See [callback security](payway_callback_security.md).

These flags are operator attestations; code never enables them automatically.
Disabled checkout returns 503 before any order creation or stock deduction.
Read-only order/history/statistics APIs do not require gateway enablement.

The callback route is POST at the path extracted from PAYWAY_CALLBACK_URL. If
the URL is unset, no callback route is registered: there is no invented default
path. Until the readiness flags pass, a configured callback route returns 503.

The official [ABA QR callback specification](https://developer.payway.com.kh/aba-qr-api-3158158f0)
provides tran_id in JSON. The route accepts at most 16 KiB and validates this ID;
every status, amount, approval, and other callback field is ignored. It delegates
to PaymentService.callback_hint for signed server-to-server verification. The
response contains no order or payment information. Duplicate paid callbacks are
idempotent. A bounded 120/minute per-worker limiter is included; configure shared
reverse-proxy rate limiting before public exposure.

Checkout commits before HTTP initialization. If initialization fails, the API
returns 503 WITH the existing OrderResponse in data and an instruction to check
that order. Do not repeat POST /checkout blindly: separate POSTs are separate
purchases; durable checkout idempotency keys are not part of the current schema.
Unknown gateway transactions and unresolved payments retain stock for review.

## Hoppscotch readiness

1. Start Flask with the existing database and obtain a customer/admin token
   through the existing auth API. Test the read APIs and disabled checkout now.
2. Configure sandbox credentials and the externally reachable callback URL;
   confirm ABA whitelisting. No credentials were added by this implementation.
3. Run the opt-in sandbox tests documented in payway_sandbox.md, then set the
   explicit approval/verification/public flags and restart the server.
4. Submit checkout; use its returned order ID for payment checks/cancellation.
   Forward fulfillment changes must fail until PayWay verifies PAID.
5. Test provider callbacks with shared rate limiting. Pending initialization
   recovery, refund review, and recurring reconciliation scheduling remain
   separate operational features. Step 7 adds the [Telegram sender](telegram_notifications.md)
   and an explicit retry entry point. Step 8 adds a [separate worker](payment_worker.md)
   for reconciliation/retries and requires PAYWAY_WORKER_VERIFIED=true before public enablement.

Automated API tests live in tests/test_order_routes.py and use a disposable
PostgreSQL schema with mocked gateway responses. They do not enable the actual
configured public endpoints or contact PayWay.
