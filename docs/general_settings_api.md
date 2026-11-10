# General Setting API

All responses use ApiResponse.success with HTTP 200 and the envelope:

```json
{"error":false,"status":"OK","message":"Success","data":{}}
```

One GeneralSettingService serves both Admin and Web. Entity options query active,
nondeleted rows only and order by name ASC, id ASC. Size's nullable name/value
remain null when absent (PostgreSQL's ASC ordering puts null names last).
There are no writes, pagination, invented ordering columns, or migrations.

| Method | Path | Authorization | data keys |
| --- | --- | --- | --- |
| GET | /api/v1/admin/setting/form/product | Admin Bearer token | categories, brands, colors, sizes |
| GET | /api/v1/admin/setting/filter/product | Admin Bearer token | categories, brands |
| GET | /api/v1/admin/setting/filter/stock-movement | Admin Bearer token | types |
| GET | /api/v1/admin/setting/filter/order | Admin Bearer token | payment_statuses, order_statuses |
| GET | /api/v1/web/setting/filter/shop | Public | categories, brands |
| GET | /api/v1/web/setting/form/order | Public | deliveries, payment-methods |
| GET | /api/v1/web/setting/filter/order | Public | order_status |

No request body is needed. In Hoppscotch, prefix paths with your Flask origin
(normally http://127.0.0.1:5000); select Bearer auth only for Admin endpoints.
Existing JWT/session/account/role authorization applies: no/invalid/revoked
token returns 401 and an authenticated nonadmin returns 403.

Example product form data:

```json
{
  "categories": [{"id": 1, "name": "Shoes"}],
  "brands": [{"id": 1, "name": "Brand"}],
  "colors": [{"id": 1, "name": "Black"}],
  "sizes": [{"id": 1, "name": "EU", "value": "42"}]
}
```

Admin product filters and public shop filters return only categories and brands
from that same shape. Stock-movement data is:

```json
{"types":[{"value":"IN","label":"In"},{"value":"OUT","label":"Out"}]}
```

StockMovementType has no label property, so its existing values are title-cased
for display. Other enums reuse their existing label properties. No statuses
or enum definitions are changed.

Example Admin order filters:

```json
{
  "payment_statuses": [
    {"value":"PENDING","label":"Pending"},
    {"value":"PAID","label":"Paid"},
    {"value":"FAILED","label":"Failed"},
    {"value":"CANCELLED","label":"Cancelled"},
    {"value":"REFUNDED","label":"Refunded"}
  ],
  "order_statuses": [
    {"value":"PENDING","label":"Pending"},
    {"value":"PROCESSING","label":"Processing"},
    {"value":"SHIPPED","label":"Shipped"},
    {"value":"DELIVERED","label":"Delivered"},
    {"value":"CANCELLED","label":"Cancelled"}
  ]
}
```

Public order filters expose the same order list under the singular key
`order_status`. Payment statuses are sourced from PaymentStatus, not OrderStatus.

Example public order form response:

```json
{
  "error": false,
  "status": "OK",
  "message": "Success",
  "data": {
    "deliveries": [{"id": 1, "name": "Delivery", "fee": 2.0, "currency": "USD"}],
    "payment-methods": [{"value": "ONLINE", "label": "Online Payment"}]
  }
}
```

Fees are JSON numbers as requested, without forcing a two-place rounding on
the five-place stored fee. This differs intentionally from the existing full
DeliveryMethodResponseSchema's string fee. JSON 2.0 and 2.00 represent the same
number. All active delivery currencies are listed; checkout's existing USD
validation still applies. Listing ONLINE does not enable checkout, certify
gateway readiness, or alter the public payment gate. COD remains unavailable.

Empty entity tables return empty arrays in the same keys, with HTTP 200. Enum
options remain present. The form/product lookup executes four entity queries,
product/shop filters two, order form one, and enum generation zero; JWT checks
may execute their existing additional authorization queries.

The locally accessible Spring GeneralSettingService/controller were empty stubs.
The response contracts in the user's request are the source for these endpoints.

Tests are in tests/test_general_setting.py and use the existing disposable
PostgreSQL schema fixture when CHECKOUT_TEST_DATABASE_URL is configured.
