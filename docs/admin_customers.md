# Admin Customer Management

All requests require `Authorization: Bearer <ADMIN_ACCESS_TOKEN>`. Authorization uses the stored role, never request fields. Responses use ApiResponse and `Cache-Control: no-store`.

## Requests

- `GET http://localhost:5000/api/v1/admin/customers?page_no=1&per_page=10&search=Dara`
- `GET http://localhost:5000/api/v1/admin/customers/1`
- `DELETE http://localhost:5000/api/v1/admin/customers/1` (no body)

List parameters: page_no >= 1, per_page 1..100, optional literal substring search across username/email/phone. Unsupported or repeated parameters return 400. Default ordering is latest non-deleted order created_at descending, then user ID descending. Out-of-range pages return an empty list. No create/update endpoints exist.

Example list item:

```json
{"id":1,"username":"Dara","email":"d@example.com","totalOrders":2,"totalSpent":"20.00","lastOrderAt":"2026-11-10 10:30:00","currency":"USD","totalSpentByCurrency":{"USD":"20.00"}}
```

Detail adds phone, profile image URL, status, and createdAt. No auth or gateway credentials are serialized. Only non-deleted users with at least one non-deleted order qualify, independent of role. ADMIN customers can be read but cannot be deleted.

## Financial interpretation

Counts include all non-deleted orders, including cancelled ones. Spending includes non-cancelled orders whose paid status, ONLINE payment approval evidence, amount, currency, and invoice match the existing OrderService verified-paid predicate. Ambiguous multiple payments, refunds, refund reviews, and soft-deleted financial evidence do not contribute. PAID_NOTIFY_PENDING is verified spending but prevents deletion until notification processing completes.

Amounts are decimal strings with two places. USD and KHR are never summed. For no verified spending, totalSpent is "0.00" and currency is null. For multiple currencies, totalSpent and currency are null; totalSpentByCurrency holds the exact separate totals. No currency conversion is inferred.

## Deletion safety

Deletion only sets the existing User soft-delete audit fields and revokes refresh sessions in one transaction. No user or financial record is hard-deleted. Even hidden orders must be resolved. Every order must be DELIVERED with fully verified payment evidence or CANCELLED with CLOSED gateway evidence and matching cancelled invoice/payment/order states. Missing or ambiguous financial records, leases, scheduled reconciliation, incomplete notifications, and refund reviews prevent deletion (400). ADMIN deletion returns 403; unqualified/deleted/missing customers return 404.

Checkout currently reads users without a row lock. A user row lock alone cannot prevent a previously validated checkout from completing after soft deletion. To avoid changing checkout, this endpoint acquires PostgreSQL ACCESS EXCLUSIVE on the users table with NOWAIT, held only during the database transaction. This conflicts with in-flight checkout eligibility reads; those requests cause deletion to return 409 immediately. New user reads wait briefly and then see the deleted flag. This is deliberately coarse: unrelated user activity may also produce 409. Retry later; do not bypass the lock. Locked order rows and existing OrderService financial checks coordinate payment transitions. No external calls occur inside deletion.

## Verification

`CHECKOUT_TEST_DATABASE_URL=<isolated-test-capable-postgresql-url>` followed by `.venv/Scripts/python.exe -m unittest tests.test_admin_customers` runs tests in a uniquely named disposable schema. It does not alter public tables or apply migrations.
