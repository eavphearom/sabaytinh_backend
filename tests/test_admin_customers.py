from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from flask_jwt_extended import create_access_token
from sqlalchemy import select, event
from app.extensions import db, jwt
from app.models import User, Role, Order, Payment, Invoice, RefreshSession
from app.exceptions.handlers import register_error_handlers
from app.security.jwt_utils import register_jwt_handlers
from app.routes.v1.admin.customer_routes import admin_customer_bp
from tests import test_checkout_service as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class AdminCustomerTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = fixture.CheckoutServicePostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.CheckoutServicePostgresTests.setUpClass.__func__(cls)
        cls.app.config["JWT_SECRET_KEY"] = "customer-test-key-never-use-in-real-application"
        jwt.init_app(cls.app)
        register_jwt_handlers(jwt)
        register_error_handlers(cls.app)
        cls.app.register_blueprint(admin_customer_bp)

    def setUp(self):
        fixture.CheckoutServicePostgresTests.setUp(self)
        db.session.add(Role(id=2, name="Administrator", code="ADMIN"))
        db.session.flush()
        db.session.add_all([
            User(id=2, username="Other", email="other@test.invalid", phone="012999", password="secret", role_id=1),
            User(id=3, username="NoOrders", email="none@test.invalid", password="secret", role_id=1),
            User(id=4, username="Admin", email="admin@test.invalid", password="secret", role_id=2),
        ])
        db.session.flush()
        self.headers = {}
        for user_id in (1, 2, 4):
            sid = uuid4()
            db.session.add(RefreshSession(id=sid, user_id=user_id, token_hash="dummy", revoked=False,
                expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            self.headers[user_id] = {"Authorization": "Bearer " + create_access_token(
                identity=str(user_id), additional_claims={"sid": str(sid)})}
        self.add_order(1, 1)
        self.add_order(2, 2, amount="30.00")
        db.session.commit()
        self.client = self.app.test_client()

    def add_order(self, id, customer, status="DELIVERED", amount="20.00", currency="USD", deleted=False):
        paid = status == "DELIVERED"
        financial = "PAID" if paid else "CANCELLED" if status == "CANCELLED" else "PENDING"
        db.session.add(Order(id=id, customer_id=customer, order_code=f"TEST-{id}",
            delivery_method_id=1, delivery_method_name="Delivery", recipient_name="Name",
            recipient_phone="123", delivery_address="Address", order_status=status,
            payment_status=financial, total_amount=Decimal(amount), currency=currency,
            is_deleted=deleted, created_at=datetime(2026, 1, 1) + timedelta(days=id)))
        db.session.flush()
        db.session.add(Payment(id=id, order_id=id, payment_method="ONLINE", payment_status=financial,
            amount=Decimal(amount), currency=currency, transaction_id=f"TEST-TRAN-{id}",
            payment_reference="verified" if paid else None,
            paid_at=datetime(2026, 1, 1) if paid else None,
            gateway_state="PAID" if paid else "CLOSED" if status == "CANCELLED" else "READY"))
        db.session.add(Invoice(id=id, order_id=id, invoice_no=f"TEST-INV-{id}",
            payment_status=financial, total_amount=Decimal(amount), currency=currency,
            paid_at=datetime(2026, 1, 1) if paid else None))
        db.session.flush()

    def request(self, suffix="", method="get", user=4):
        return getattr(self.client, method)("/api/v1/admin/customers" + suffix,
            headers=self.headers.get(user, {}))

    def test_qualification_and_aggregation(self):
        self.add_order(3, 1, "CANCELLED")
        self.add_order(4, 1, deleted=True)
        db.session.commit()
        result = self.request().json
        self.assertEqual(result["pagination"]["total"], 2)
        self.assertEqual([r["id"] for r in result["data"]], [1, 2])
        row = result["data"][0]
        self.assertEqual(row["totalOrders"], 2)
        self.assertEqual(row["totalSpent"], "20.00")
        self.assertEqual(self.request("/3").status_code, 404)
        self.assertEqual(self.request("/999").status_code, 404)

    def test_financial_evidence_and_duplicate_payments(self):
        for field, value in (("payment_reference", None), ("gateway_state", "REFUND_REVIEW"),
                             ("payment_status", "REFUNDED"), ("amount", Decimal("1"))):
            payment = db.session.get(Payment, 1)
            original = getattr(payment, field)
            setattr(payment, field, value); db.session.commit()
            self.assertEqual(self.request("/1").json["data"]["totalSpent"], "0.00")
            setattr(payment, field, original); db.session.commit()
        db.session.add(Payment(id=99, order_id=1, payment_method="ONLINE", amount=20, currency="USD"))
        db.session.commit()
        self.assertEqual(self.request("/1").json["data"]["totalSpent"], "0.00")

    def test_pagination_search_empty_and_validation(self):
        for search in ("Other", "other@test", "012999"):
            result = self.request("?search=" + search).json
            self.assertEqual([r["id"] for r in result["data"]], [2])
        self.assertEqual(self.request("?search=%25").json["data"], [])
        self.assertEqual(self.request("?per_page=1&page_no=2").json["data"][0]["id"], 1)
        self.assertEqual(self.request("?page_no=99").json["data"], [])
        for query in ("page_no=0", "page_no=x", "per_page=101", "include_deleted=true", "search=a&search=b", "page_no=999999999999999999999"):
            self.assertEqual(self.request("?" + query).status_code, 400, query)

    def test_auth_and_safe_profile(self):
        for suffix, method in (("", "get"), ("/2", "get"), ("/2", "delete")):
            self.assertEqual(self.request(suffix, method, user=0).status_code, 401)
            self.assertEqual(self.request(suffix, method, user=1).status_code, 403)
        profile = self.request("/2").json["data"]
        self.assertEqual(profile["phone"], "012999")
        self.assertEqual(profile["totalOrders"], 1)
        self.assertEqual(profile["totalSpent"], "30.00")
        for key in ("password", "refresh_sessions", "auth_providers", "payment_reference", "token"):
            self.assertNotIn(key, profile)
        self.assertEqual(self.request().headers["Cache-Control"], "no-store")
        self.assertEqual(self.request("", "post").status_code, 405)

    def test_delete_preserves_records_and_other_users(self):
        response = self.request("/1", "delete")
        self.assertEqual(response.status_code, 200, response.json)
        db.session.expire_all()
        user = db.session.get(User, 1)
        self.assertTrue(user.is_deleted)
        self.assertEqual(user.deleted_uid, 4)
        self.assertIsNotNone(user.deleted_at)
        for model in (Order, Payment, Invoice):
            self.assertFalse(db.session.get(model, 1).is_deleted)
        self.assertFalse(db.session.get(User, 2).is_deleted)
        self.assertTrue(all(s.revoked for s in db.session.scalars(select(RefreshSession).where(RefreshSession.user_id == 1))))
        self.assertEqual(self.request("/1").status_code, 404)
        self.assertEqual(self.request().json["pagination"]["total"], 1)

    def test_delete_rejects_admin_and_unqualified(self):
        self.add_order(3, 4); db.session.commit()
        self.assertEqual(self.request("/4", "delete").status_code, 403)
        self.assertEqual(self.request("/3", "delete").status_code, 404)

    def test_delete_rejects_unresolved_and_hidden_orders(self):
        self.add_order(3, 1, "PENDING", deleted=True); db.session.commit()
        self.assertEqual(self.request("/1", "delete").status_code, 400)
        self.assertFalse(db.session.get(User, 1).is_deleted)

    def test_delete_rejects_review_and_pending_notifications(self):
        for state in ("REFUND_REVIEW", "PAID_NOTIFY_PENDING", "RECONCILE_REQUIRED"):
            db.session.get(Payment, 1).gateway_state = state; db.session.commit()
            self.assertEqual(self.request("/1", "delete").status_code, 400)
            self.assertFalse(db.session.get(User, 1).is_deleted)

    def test_cancelled_customer_deletion_requires_closed_evidence(self):
        order = db.session.get(Order, 1); order.order_status = "CANCELLED"; order.payment_status = "CANCELLED"
        payment = db.session.get(Payment, 1); payment.payment_status = "CANCELLED"; payment.gateway_state = "CLOSED"
        db.session.get(Invoice, 1).payment_status = "CANCELLED"; db.session.commit()
        self.assertEqual(self.request("/1", "delete").status_code, 200)

    def test_concurrent_customer_read_blocks_delete_safely(self):
        db.session.rollback()
        with db.engine.connect() as other:
            transaction = other.begin()
            other.execute(select(User.id).where(User.id == 1)).all()
            self.assertEqual(self.request("/1", "delete").status_code, 409)
            transaction.rollback()
        self.assertFalse(db.session.get(User, 1).is_deleted)
        db.session.rollback()
        self.assertEqual(self.request("/1", "delete").status_code, 200)

    def test_currencies_are_never_added_together(self):
        self.add_order(3, 1, amount="4000", currency="KHR"); db.session.commit()
        row = self.request("/1").json["data"]
        self.assertIsNone(row["totalSpent"])
        self.assertEqual(row["totalSpentByCurrency"], {"USD": "20.00", "KHR": "4000.00"})

    def test_list_query_count_is_bounded(self):
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            self.assertEqual(self.request().status_code, 200)
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        self.assertLessEqual(len(statements), 6)  # session, admin, role, count, page, spending
