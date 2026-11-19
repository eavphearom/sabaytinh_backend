import os
import unittest
from decimal import Decimal
from unittest.mock import patch
from app.extensions import db
from app.models import Invoice, Order, OrderItem
from app.routes.v1.web.order_routes import web_order_bp
from tests import test_admin_customers as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "Temporary PostgreSQL required")
class InvoiceApiTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.AdminCustomerTests.tearDownClass.__func__)
    tearDown = fixture.AdminCustomerTests.tearDown
    setUp = fixture.AdminCustomerTests.setUp
    add_order = fixture.AdminCustomerTests.add_order

    @classmethod
    def setUpClass(cls):
        fixture.AdminCustomerTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(web_order_bp)

    def get(self, order=1, user=1, pdf=False):
        return self.client.get(f"/api/v1/web/orders/{order}/invoice" + ("/pdf" if pdf else ""), headers=self.headers.get(user, {}))

    def test_authentication_ownership_missing_and_soft_deletion(self):
        for pdf in (False, True):
            self.assertEqual(self.get(user=0, pdf=pdf).status_code, 401)
            self.assertEqual(self.get(order=2, pdf=pdf).status_code, 404)
            self.assertEqual(self.get(order=9999, pdf=pdf).status_code, 404)
            self.assertEqual(self.get(order=2, user=2, pdf=pdf).status_code, 200)
        invoice = db.session.get(Invoice, 1)
        invoice.is_deleted = True; db.session.commit()
        self.assertEqual(self.get().status_code, 404)
        invoice.is_deleted = False
        db.session.get(Order, 1).is_deleted = True; db.session.commit()
        self.assertEqual(self.get(pdf=True).status_code, 404)

    def test_snapshot_items_totals_currency_and_no_sensitive_fields(self):
        db.session.add_all([OrderItem(id=i, order_id=1, product_id=1, variant_id=1, variant_stock_id=1,
            product_name="Original name", sku="SNAPSHOT", quantity=2, unit_price=Decimal("9.00"),
            subtotal=Decimal("18.00"), is_deleted=(i == 2)) for i in (1, 2)])
        invoice = db.session.get(Invoice, 1)
        invoice.subtotal = Decimal("18.00"); invoice.shipping_fee = Decimal("3.00")
        invoice.discount_amount = Decimal("1.00"); invoice.currency = "KHR"
        db.session.commit()
        response = self.get()
        self.assertEqual(response.status_code, 200, response.json)
        data = response.json["data"]
        self.assertEqual((data["subtotal"], data["total_amount"], data["currency"]), ("18.00", "20.00", "KHR"))
        self.assertEqual(len(data["items"]), 1)
        self.assertEqual(data["items"][0]["unit_price"], "9.00")
        self.assertEqual(data["items"][0]["product_name"], "Original name")
        for key in ("payments", "password", "payment_reference", "qr_image", "gateway_lease_token"):
            self.assertNotIn(key, data)
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_pdf_is_attachment_and_read_only_even_for_pending_invoice(self):
        invoice = db.session.get(Invoice, 1)
        invoice.payment_status = "PENDING"; invoice.paid_at = None
        db.session.commit()
        with patch("app.services.payments.payway_client.PayWayClient.verify", side_effect=AssertionError("No gateway calls")):
            response = self.get(pdf=True)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "application/pdf")
        self.assertTrue(response.data.startswith(b"%PDF-"))
        self.assertIn("attachment", response.headers["Content-Disposition"])
        self.assertIn("invoice-1.pdf", response.headers["Content-Disposition"])
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        db.session.expire_all()
        self.assertEqual(db.session.get(Invoice, 1).payment_status.value, "PENDING")
