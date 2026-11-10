import os
import unittest
from datetime import datetime
from unittest.mock import patch
from sqlalchemy import event
from app.extensions import db
from app.models import Order, Payment, Invoice, User, VariantStock, Variant, Product
from app.routes.v1.admin.dashboard_routes import admin_dashboard_bp
from tests import test_admin_customers as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class AdminDashboardTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.AdminCustomerTests.tearDownClass.__func__)
    tearDown = fixture.AdminCustomerTests.tearDown
    setUp = fixture.AdminCustomerTests.setUp
    add_order = fixture.AdminCustomerTests.add_order

    @classmethod
    def setUpClass(cls):
        fixture.AdminCustomerTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(admin_dashboard_bp)

    def get(self, user=4, now=datetime(2026, 11, 10, 10, 30)):
        with patch("app.services.dashboard_service.DateUtil.now", return_value=now):
            return self.client.get("/api/v1/admin/dashboard/overview", headers=self.headers.get(user, {}))

    def periods(self):
        db.session.get(Order, 1).created_at = datetime(2026, 10, 1)
        db.session.get(Payment, 1).paid_at = datetime(2026, 10, 31, 23, 59, 59)
        db.session.get(Order, 2).created_at = datetime(2026, 11, 1)
        db.session.get(Payment, 2).paid_at = datetime(2026, 11, 1)
        db.session.commit()

    def test_revenue_month_boundaries_and_totals(self):
        self.periods()
        data = self.get().json["data"]
        usd = next(r for r in data["total_revenue"] if r["currency"] == "USD")
        self.assertEqual(usd, dict(currency="USD", value="50.00", current_month="30.00", previous_month="20.00", percentage_change=50.0))
        for key in ("orders", "customers"):
            self.assertEqual(data[key], dict(value=2, current_month=1, previous_month=1, percentage_change=0.0))
        self.assertEqual(data["metadata"]["timezone"], "Asia/Phnom_Penh")

    def test_distinct_customers_and_earliest_order(self):
        self.periods()
        self.add_order(3, 1, "PENDING")
        db.session.get(Order, 3).created_at = datetime(2026, 11, 2)
        db.session.commit()
        data = self.get().json["data"]
        self.assertEqual(data["orders"]["value"], 3)
        self.assertEqual(data["orders"]["percentage_change"], 100.0)
        self.assertEqual(data["customers"]["value"], 2)
        self.assertEqual(data["customers"]["current_month"], 1)
        db.session.get(User, 2).is_deleted = True
        db.session.commit()
        self.assertEqual(self.get().json["data"]["customers"]["value"], 1)

    def test_revenue_requires_verified_evidence(self):
        for field, value in (("payment_reference", None), ("gateway_state", "REFUND_REVIEW"),
                             ("payment_status", "REFUNDED"), ("payment_status", "FAILED"), ("is_deleted", True)):
            payment = db.session.get(Payment, 1); original = getattr(payment, field)
            setattr(payment, field, value); db.session.commit()
            self.assertEqual(self.get().json["data"]["total_revenue"][0]["value"], "30.00")
            setattr(payment, field, original); db.session.commit()
        db.session.get(Order, 1).order_status = "CANCELLED"; db.session.commit()
        self.assertEqual(self.get().json["data"]["total_revenue"][0]["value"], "30.00")

    def test_currencies_and_zero_baseline(self):
        self.add_order(3, 1, currency="KHR", amount="4000")
        db.session.get(Payment, 3).paid_at = datetime(2026, 11, 2)
        db.session.commit()
        data = self.get().json["data"]
        currencies = {r["currency"]: r for r in data["total_revenue"]}
        self.assertEqual(currencies["USD"]["value"], "50.00")
        self.assertEqual(currencies["KHR"]["value"], "4000.00")
        self.assertIsNone(currencies["KHR"]["percentage_change"])

    def test_inventory_thresholds_and_visibility(self):
        db.session.get(VariantStock, 1).qty = 2
        db.session.get(VariantStock, 1).low_stock_alert = 2
        db.session.get(VariantStock, 2).qty = 0
        db.session.commit()
        self.assertEqual(self.get().json["data"]["low_stock"], dict(value=1, out_of_stock=1, percentage_change=None))
        db.session.get(VariantStock, 1).low_stock_alert = 1; db.session.commit()
        self.assertEqual(self.get().json["data"]["low_stock"]["value"], 0)
        db.session.get(VariantStock, 1).low_stock_alert = 2; db.session.commit()
        for model, field in ((VariantStock, "is_deleted"), (Variant, "is_active"), (Product, "is_active")):
            record = db.session.get(model, 1); original = getattr(record, field)
            setattr(record, field, field == "is_deleted"); db.session.commit()
            self.assertEqual(self.get().json["data"]["low_stock"]["value"], 0)
            setattr(record, field, original); db.session.commit()

    def test_empty_eligible_data(self):
        for id in (1, 2):
            db.session.get(Order, id).is_deleted = True
            db.session.get(VariantStock, id).is_deleted = True
        db.session.commit()
        data = self.get().json["data"]
        for key in ("orders", "customers", "low_stock"):
            self.assertEqual(data[key]["value"], 0)
            self.assertIsNone(data[key]["percentage_change"])
        for revenue in data["total_revenue"]:
            self.assertEqual(revenue["value"], "0.00")
            self.assertIsNone(revenue["percentage_change"])

    def test_january_rollover_and_authorization(self):
        self.assertEqual(self.get(user=0).status_code, 401)
        self.assertEqual(self.get(user=1).status_code, 403)
        response = self.get(now=datetime(2027, 1, 10))
        self.assertEqual(response.json["data"]["metadata"]["previous_month_start"], "2026-12-01T00:00:00")
        self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_constant_query_count(self):
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            self.assertEqual(self.get().status_code, 200)
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        self.assertLessEqual(len(statements), 7)


    def test_empty_domain_tables(self):
        for model in (Invoice, Payment, Order, VariantStock):
            db.session.execute(model.__table__.delete())
        db.session.commit()
        response = self.get()
        self.assertEqual(response.status_code, 200)
        for key in ("orders", "customers", "low_stock"):
            self.assertEqual(response.json["data"][key]["value"], 0)

    def test_ambiguous_payments_and_invoice_mismatch_excluded(self):
        db.session.get(Invoice, 1).total_amount = 1
        db.session.commit()
        self.assertEqual(self.get().json["data"]["total_revenue"][0]["value"], "30.00")
        db.session.get(Invoice, 1).total_amount = 20
        db.session.add(Payment(id=99, order_id=1, payment_method="ONLINE", amount=20, currency="USD"))
        db.session.commit()
        self.assertEqual(self.get().json["data"]["total_revenue"][0]["value"], "30.00")
