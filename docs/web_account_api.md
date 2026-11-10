# Web Account APIs

Both GET endpoints require a valid customer JWT and session using the existing
customer_required decorator. Ownership always comes from g.customer_id; callers
cannot select another customer. Responses use Cache-Control: no-store. No payment
or checkout operations are performed.

## Overview

`GET /api/v1/web/account/overview` accepts no query parameters or request body.
It reuses OrderRepository.get_account_overview's single aggregate query.
All counts exclude soft-deleted orders and other customers. totalOrders includes
CANCELLED; inProgress includes PENDING/PROCESSING/SHIPPED; completed includes
DELIVERED. Missing orders yield zeros.

```json
{
  "error": false,
  "status": "OK",
  "message": "Success",
  "data": {"totalOrders": 10, "inProgress": 4, "completed": 5}
}
```

## History

`GET /api/v1/web/account/orders`

| Parameter | Contract |
| --- | --- |
| page_no | 1-based; default 1 |
| per_page | 1–100; default 10 |
| search | Case-insensitive literal substring of order_code only |
| status | PENDING, PROCESSING, SHIPPED, DELIVERED or CANCELLED |
| sort_by | id, createdAt or total; default createdAt |
| sort_dir | asc or desc; default desc |

Pagination parameter names and metadata remain the existing Flask snake_case
convention. Response order fields use camelCase. Unknown/repeated parameters,
invalid status/sort/pagination, or include_deleted/customer_id attempts return
400. The shared pagination utility uses ID ascending for equal sort values.
No new status, date filter or payment-status filter is introduced.

Example data item:

```json
{
  "id": 1,
  "orderCode": "ORD-001",
  "createdAt": "2026-11-10T10:30:00",
  "total": 45.0,
  "orderStatus": "PENDING",
  "paymentStatus": "PENDING",
  "totalItems": 2,
  "previewItem": {
    "productName": "Nike Shoes",
    "image": "http://127.0.0.1:5000/uploads/products/shoe.png",
    "colorName": "Black",
    "sizeName": "42",
    "quantity": 1,
    "unitPrice": 40.0
  }
}
```

The list is wrapped in ApiResponse.paginate with data and pagination containing
per_page, total, total_page and page_no. Empty pages return 200 with data=[].
Amounts are JSON numbers as requested (45.0 and 45.00 are the same JSON numeric
value); database amounts and financial calculations remain Decimal. Timestamps
retain the stored local time without inventing a UTC suffix/timezone conversion.
Image URLs use the existing ImageURLField/FileUtil utility.

totalItems counts nondeleted OrderItem rows, not their quantities. previewItem
uses the lowest-ID nondeleted row and is null if none exists. All page items are
batch-loaded through selectinload; a nonempty page uses three queries: count,
orders, and items. Authentication adds its existing session/user queries.

The shared OrderRepository history query now has an explicit account projection
option for order-code-only search and loading items only. Its existing default
behavior is unchanged. /api/v1/web/orders still returns snake_case fields, sums
quantities for total_items, and supports its existing filters; the legacy
account-overview endpoint also keeps its original response keys.

## Hoppscotch

Use Authorization: Bearer <customer-access-token>, no request body:

```text
GET http://127.0.0.1:5000/api/v1/web/account/overview
GET http://127.0.0.1:5000/api/v1/web/account/orders?page_no=1&per_page=10
GET http://127.0.0.1:5000/api/v1/web/account/orders?search=ORD-001&status=PENDING&sort_by=createdAt&sort_dir=desc
GET http://127.0.0.1:5000/api/v1/web/account/orders?sort_by=total&sort_dir=asc
```

Valid requests return 200. Missing/invalid/revoked JWTs return 401 under existing
authentication handlers. No account controller/service implementation was found
in the accessible Spring project; the supplied user contract defines this adapter.

Tests: tests/test_web_account.py, using the existing isolated PostgreSQL schema
fixture when CHECKOUT_TEST_DATABASE_URL is configured. No migrations are needed.
