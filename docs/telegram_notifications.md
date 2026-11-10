# Telegram payment notifications

`PaymentService()` now defaults to `TelegramNotificationService.notify_verified_payment`.
Custom injected hooks remain supported. The existing PayWay verifier commits PAID
and its notification marker before calling the hook. No checkout, verification,
inventory, public API flags, callback registration, or database schema changed.

Configure `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` in the environment and restart
Flask. The bot must have permission to send to that chat. Blank/invalid credentials
leave events pending; they do not discard events or affect payment success.
No real Telegram messages are sent by the tests. Credentials are never logged.

The adapter uses the official [sendMessage API](https://core.telegram.org/bots/api#sendmessage)
at `https://api.telegram.org`, with TLS verification, a five-second connection
timeout, fifteen-second socket timeout, bounded response size, and no redirects.
Messages use plain text without parse_mode/entities, so HTML/Markdown characters
remain literal. Embedded newlines/control characters in customer data are removed.
Link previews are disabled. Long fields/product lists are truncated to fit one
message; omitted product lines are indicated. No gateway credentials, QR data,
or authentication records appear in messages.

Example (illustrative):

```text
Payment verified
Order: ORD-20261110-001
Customer: Dara
Total: 21.50 USD
Payment: ONLINE / PAID
Recipient: Sok Dara
Phone: 012345678
Address: Street 271, Phnom Penh, Cambodia
Event: payment:42:paid
Products:
- Shoe x 2
```

## Durable state and retries

The stable event identity is `payment:<payment_id>:paid`. The existing payment
row stores `PAID_NOTIFY_PENDING` atomically with verified payment, then a fenced
90-second delivery lease. Concurrent dispatchers skip an active lease. A known
successful send changes the marker to `PAID`, durably suppressing subsequent
callbacks/retries even after application restart. Network I/O holds no DB locks.

Failures retain the pending marker and cannot undo the paid order/invoice.
Ordinary failures defer retry for 90 seconds. A Telegram 429 defers for at least
its documented `retry_after` (minimum 90 seconds); invalid rate-limit metadata
defers for seven days. Other HTTP errors, including authorization errors, stay
pending until configuration is fixed and an operator retries. There is no
inline retry loop. Step 8's separate [worker](payment_worker.md) schedules retries. Eligible batches exclude
active leases before applying the batch limit.

For recovery, in a Flask application context with no unrelated pending writes:

```python
from app.services.notifications.telegram_notification_service import TelegramNotificationService
delivered_count = TelegramNotificationService().retry_pending(limit=100)
```

Repeated ABA callbacks alone do not drain previously failed notifications.
Use the recovery entry point explicitly or run the separate worker. Without either,
pending messages will not be retried automatically. Cancelled orders (including
late verified payments requiring refund review) are never sent as successful
purchase notifications; their existing refund-review pending marker is retained
for a separate operator workflow. Nonpaid/unverified payments are rejected.

## Delivery limits and required future persistence

This is at-least-once attempted delivery with durable acknowledgement, **not
exactly-once Telegram delivery**. Telegram sendMessage has no idempotency-key
parameter. If Telegram accepted a message before a timeout, process crash, or
failed local acknowledgement, retry can send it again. A worker stalled beyond
its lease can also overlap a retry. The visible event ID assists manual matching;
it does not make Telegram deduplicate messages. Current storage does not retain
Telegram message IDs, destination, immutable payloads, or attempt history.
Pending messages are rendered from current order data and use the configured
chat at retry time. Restart recovery tests replace sessions/service instances
against PostgreSQL; they do not kill a running application process.

For a fully managed delivery workflow, add a transactional outbox with unique
event/channel identity, destination and payload snapshot, delivery state,
attempt count, next-attempt time, lease, Telegram message ID, and sanitized
failure/uncertain-outcome records. Insert it alongside the PAID transaction,
then process with a worker. No such table or migration was added in this step.
Even an outbox alone cannot eliminate Telegram's accepted-but-unacknowledged
window: ambiguous outcomes need an explicit retry-versus-manual-review policy,
or a delivery endpoint supporting idempotency. Do not promise exactly once.

## Validation

`python -m unittest tests.test_telegram_notification_service` runs mocked HTTPS
tests. Set `CHECKOUT_TEST_DATABASE_URL` to enable PostgreSQL integration tests in
an isolated disposable schema. Tests cover committed payment visibility before
send, duplicate callbacks, concurrent dispatch, acknowledgement/retry persistence
with fresh sessions, rate limits, missing credentials, HTTP/protocol failures,
timeouts, cancelled/unverified exclusions, and the ambiguous-delivery limitation.
