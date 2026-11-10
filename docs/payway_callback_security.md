# PayWay callback authentication and Spring compatibility

The callback now requires `PAYWAY_CALLBACK_SECRET` and the
`X-PayWay-HMAC-SHA512` header. Configure the secret locally; it is distinct from
`PAYWAY_API_KEY` and has no fallback. The supplied Spring source confirms that
its `PAYWAY_PUBLIC_KEY` is the outbound HMAC secret: place that verified sandbox
credential in Flask's `PAYWAY_API_KEY`. No RSA key is used or needed by this
implementation. No readiness flags or actual credentials were changed.

## Outbound requests

Existing signing remains unchanged: UTF-8 secret/message, raw HMAC-SHA512 digest,
then Base64. QR concatenation is req_time, merchant_id, tran_id, amount, items,
first_name, last_name, email, phone, purchase_type, payment_option, callback_url,
return_deeplink, currency, custom_fields, return_params, payout, lifetime,
qr_image_template. Check/Close concatenate req_time + merchant_id + tran_id.
Tests verify all 19 QR fields and both transaction operations independently.

## Callback representation

The implementation follows the supplied PayWayHashService methods:

- Sort only top-level keys using Java String/TreeMap UTF-16 ordering.
- Concatenate top-level value representations without separators or key names.
- Top-level null/false become empty text; true becomes `1`; strings stay raw.
- Numbers use plain decimal notation with trailing fractional zeros removed;
  negative zero becomes `0`. No scientific notation or float rounding is added.
- Nested arrays/objects become compact JSON, retaining nested insertion order.
  Nested booleans/null use their JSON literals. Strings/keys are quoted; `/`
  becomes `\/`; non-ASCII UTF-16 units use lowercase `\uXXXX` escapes, including
  surrogate pairs. ASCII control escaping follows Jackson conventions.
- Compute HMAC-SHA512 with PAYWAY_CALLBACK_SECRET and compare decoded digest
  bytes with `hmac.compare_digest`. The header is strict canonical Base64 of a
  64-byte digest. No alternative serialization or unsigned fallback is accepted.

Input protection remains stricter than Spring's shown helper: a 16 KiB byte
limit (Spring checks 65,536 Java characters), UTF-8 JSON object only, no duplicate
keys, unpaired surrogates, nonfinite numbers, excessive nesting (32), or numeric
expansion beyond adjusted decimal exponent +/-1024. Flask parses numbers as
Decimal to preserve their precision. Spring's ObjectMapper numeric-node settings
were not supplied: if it uses default DoubleNode rather than DecimalNode, unusual
high-precision numeric inputs may round before decimalValue(). Confirm those
settings or provide a high-precision signed test vector before claiming universal
numeric equivalence. Ordinary two-decimal payment values are covered by tests.

With the public gate satisfied, missing/malformed/invalid signatures return 401,
malformed JSON/content type returns 400, excessive bodies return 413. Missing
server-side secret returns 503 and prevents public payment readiness. The closed
public gate still returns 503 before processing callbacks. Spring's shown helper
instead reports its parse/config failures as Unauthorized and Java may accept
unpadded Base64; these stricter transport/error behaviors are intentional.

Only after authentication and transaction-ID validation does the route invoke
`PaymentService.callback_hint()`. It independently checks PayWay and matches
transaction, amount, currency and approval evidence before committing PAID.
Signed status claims are never financial authority. Repeated authentic callbacks
remain idempotent through existing payment state/leases and notification markers;
HMAC alone does not provide timestamp-based replay prevention.

## Official documentation differences needing ABA confirmation

The [official callback PHP example](https://developer.payway.com.kh/unschedule-payment-2038908m0)
sorts top-level keys then uses array_walk_recursive to concatenate leaf values.
It does **not** JSON-serialize nested objects/arrays as the supplied Spring helper
does. PHP numeric string conversion can also differ from plain BigDecimal output.
This example appears under Credentials on File, not the
[QR callback guide](https://developer.payway.com.kh/folder-3158158).

The reviewed QR guide requires independent Check Transaction verification but
does not specify this exact HMAC header, separate secret provisioning, or the
Spring nested-value representation. The implemented header/secret contract comes
from the user's verified Spring source. Confirm with ABA that this sandbox
merchant's QR callbacks use it, including nested/numeric test vectors. Do not
disable HMAC verification to accommodate an unsigned callback. Use the existing
reconciliation worker while callback compatibility is being investigated.

No real signed ABA callback was received during implementation. Automated tests
use test-only keys and cover malformed inputs, limits, decimals, nested values,
Unicode/emoji escaping, constant-time comparison, independent financial checks,
and duplicate callbacks. No secret, signature or callback body is logged.
