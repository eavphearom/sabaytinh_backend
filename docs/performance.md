# Request latency investigation

Read-only measurements on 2026-11-19 (single samples, not a load test):

- Production health GET: 360 ms; products GET: 1,366 ms.
- Production `x-vercel-id` indicated Singapore edge / Washington function (`sin1::iad1`).
- Configured Supabase database is in ap-southeast-2 (Sydney).
- Local SELECT 1 including connection/transaction overhead: 4,484 ms on first use,
  991 ms on reuse. Local development still accesses the remote database.

## Changes

- `vercel.json` selects `syd1` so backend SQL round trips stay near the database.
  Verify the production DATABASE_URL uses the same database region before deploying.
- JWT session validation eagerly loads its owner and role. Auth decorators and
  `/auth/me` reuse that request's result: three SELECTs become one. No cross-request
  auth cache; revocation, account status, soft deletion and role checks remain active.
- Order details join scalar relationships and batch-load collections: seven
  SELECTs become four. Order pagination uses four including its count instead of
  five, and does not fetch the large payment QR image column. Detail/resume still
  retain the original image.
- Admin React navigation no longer waits an artificial 350 ms; Suspense still
  shows loading when a page's code actually needs loading.

## Deployment and validation

Push/redeploy the backend and Admin projects separately. No migration, payment
readiness change or credential change is required. Confirm the deployed function
region is Sydney in Vercel. Compare several warm and cold GET timings in browser
Network tools, especially `/api/v1/auth/me`, products and order details. Do not
trigger payments to benchmark latency. Production improvements are not measured
until these changes are deployed.

For fast local development, use a separate local PostgreSQL development database
and test fixtures. Do not copy production secrets or switch production to a local
database. The code optimizations reduce remote round trips but cannot remove the
network latency of a remote database.

Vercel recommends colocating functions with their data source:
https://vercel.com/docs/functions/configuring-functions/region
Sydney region mapping: https://vercel.com/docs/regions
