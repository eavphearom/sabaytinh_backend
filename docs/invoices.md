# Customer invoices

Both endpoints require the existing customer Bearer JWT and enforce ownership:

- `GET /api/v1/web/orders/{order_id}/invoice`: ApiResponse.success with invoice
  number, order code/status, delivery recipient/address, recorded payment status,
  dates, currency, totals as two-decimal strings, and all non-deleted item snapshots.
- `GET /api/v1/web/orders/{order_id}/invoice/pdf`: application/pdf attachment,
  `invoice-{invoice_id}.pdf`. Responses are no-store.

Missing, deleted, and another customer's invoices return 404; missing/invalid
authentication returns 401. No gateway requests, financial writes, new invoice
creation or price recalculation occur. A pending invoice remains visibly PENDING;
its existence is not evidence of payment. The website retains its existing
Paid/Refunded eligibility for opening invoices from Order Details.

## UI

Account > My Orders > Order Details > View Invoice opens the invoice preview.
Download PDF fetches the protected attachment using the existing Axios token
interceptor. It validates the PDF header, handles JSON error blobs, and releases
the temporary download URL. Back returns to the existing order details.

Design: orange accent, recipient and invoice details, all item rows with quantities
and recorded prices, subtotal/delivery/discount/total, payment badge, footer.
PDFs support pagination, repeated item headings, and embedded English/Khmer fonts.
No remote images/fonts are fetched while generating a PDF. Other writing systems
outside the bundled Noto Sans/Khmer coverage have not been validated.

## Deployment

Install updated requirements and restart Flask; redeploy backend and website.
`reportlab[shaping]==5.1.0` is required for PDF generation. Commit
`app/assets/fonts/` including its OFL licenses; vercel.json explicitly includes
these assets. No database migration or new environment variables are needed.
PDF files are generated in memory, not stored in public uploads.

## Changed files

Backend: invoice_repository.py; web/order_routes.py; schemas/invoice_schema.py;
services/invoice_service.py; services/invoice_pdf_service.py; requirements.txt;
vercel.json; app/assets/fonts/; tests/test_invoice_api.py; tests/test_invoice_pdf.py;
this document.

Website: OrderDetailsModal.jsx; InvoiceModal.jsx; services/invoiceService.js;
services/invoiceDownload.js; tests/invoice-download.test.mjs.

Validation: 32 invoice/order API/repository/PDF tests passed using temporary local
PostgreSQL; 34 website tests passed; production build passed (existing bundle-size
warning). PDF sample visually checked with English and Khmer; a 70-item document
paginated to seven pages with the final item present. No live payment calls or
production data writes. Hosted deployment and real browser download remain a
post-deployment smoke check.
