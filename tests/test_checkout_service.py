"""PostgreSQL integration tests in a disposable, uniquely named schema.

Set CHECKOUT_TEST_DATABASE_URL to a PostgreSQL URL with CREATE SCHEMA permission.
No migration is applied and no public table is created, modified, or dropped.
"""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import os
from threading import Barrier
import unittest
from unittest.mock import patch
from uuid import uuid4

from flask import Flask
from marshmallow import ValidationError
import sqlalchemy as sa
from sqlalchemy.schema import CreateSchema, DropSchema

from app.extensions import db
from app.models import (
    Role, User, Category, Brand, Unit, Color, Size, Product, ProductUnit,
    Variant, VariantStock, VariantImage, DeliveryMethod, Order, OrderItem,
    Payment, Invoice, OrderStatusHistory, StockMovement,
)
from app.exceptions.api_exception import BadRequestException, DuplicateException, UnauthorizedException
from app.services.checkout_service import CheckoutService
from app.services.variant_stock_service import VariantStockService


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class CheckoutServicePostgresTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        url = os.environ["CHECKOUT_TEST_DATABASE_URL"]
        if sa.engine.make_url(url).get_backend_name() != "postgresql":
            raise unittest.SkipTest("Real PostgreSQL is required")
        cls.schema = "checkout_test_" + uuid4().hex
        cls.admin_engine = sa.create_engine(url, connect_args={"connect_timeout": 5})
        with cls.admin_engine.begin() as conn:
            conn.execute(CreateSchema(cls.schema))
        cls.app = Flask(__name__)
        cls.app.config.update(
            TESTING=True, SQLALCHEMY_DATABASE_URI=url,
            SQLALCHEMY_ENGINE_OPTIONS={
                "execution_options": {"schema_translate_map": {None: cls.schema}},
                "connect_args": {"connect_timeout": 5, "options": "-c lock_timeout=10000 -c statement_timeout=20000"},
            },
        )
        db.init_app(cls.app)
        try:
            with cls.app.app_context():
                db.create_all()
        except Exception:
            cls.tearDownClass()
            raise

    @classmethod
    def tearDownClass(cls):
        # Restrict cleanup to this generated schema; never use CASCADE.
        assert cls.schema.startswith("checkout_test_") and len(cls.schema) == 46
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()
        with cls.admin_engine.begin() as conn:
            conn.execute(DropSchema(cls.schema))
        cls.admin_engine.dispose()

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        for table in reversed(db.metadata.sorted_tables):
            db.session.execute(table.delete())
        db.session.commit()
        db.session.add_all([
            Role(id=1, name="Customer", code="USER"),
            Category(id=1, name="Shoes", slug="shoes"),
            Brand(id=1, name="Brand", slug="brand"),
            Unit(id=1, name="Pair", code="PAIR"),
            Color(id=1, name="Black"),
            Size(id=1, name="Size", value="42"),
            Size(id=2, name="Size", value="43"),
            DeliveryMethod(id=1, name="Delivery", code="DELIVERY", fee=Decimal("1.235"), currency="USD"),
        ])
        db.session.flush()
        db.session.add(User(id=1, username="Dara", email="d@example.com", password="hash", role_id=1))
        db.session.add(Product(id=1, category_id=1, brand_id=1, unit_id=1, code="PRD00001", name="Shoe", slug="shoe"))
        db.session.flush()
        db.session.add(ProductUnit(id=1, product_id=1, unit_id=1, multiplier=Decimal("1")))
        db.session.add(Variant(id=1, product_id=1, color_id=1, sku_prefix="PRD00001-BLACK", price=Decimal("10.125"), is_default=True))
        db.session.flush()
        db.session.add_all([
            VariantStock(id=1, variant_id=1, size_id=1, unit_id=1, sku="BLACK-42", qty=5),
            VariantStock(id=2, variant_id=1, size_id=2, unit_id=1, sku="BLACK-43", qty=5),
            VariantImage(id=1, variant_id=1, image="/uploads/products/a.png", is_primary=True),
        ])
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def payload(self, quantity=2):
        return dict(delivery_method_id=1, recipient_name="Sok Dara", recipient_phone="012345678",
                    delivery_address="Phnom Penh", note="Call me", payment_method="ONLINE",
                    items=[dict(variant_stock_id=1, quantity=quantity)])

    def assert_no_checkout(self):
        for model in (Order, OrderItem, Payment, Invoice, OrderStatusHistory, StockMovement):
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(model)), 0)
        self.assertEqual(db.session.get(VariantStock, 1, populate_existing=True).qty, 5)
        self.assertEqual(db.session.get(VariantStock, 2, populate_existing=True).qty, 5)

    def test_success_snapshots_money_and_movements(self):
        with patch.object(db.session, "commit", wraps=db.session.commit) as commit:
            result = CheckoutService().checkout(1, self.payload())
            self.assertEqual(commit.call_count, 1)
        order = db.session.get(Order, result["order_id"])
        self.assertEqual(order.order_code, f"ORD{order.id:05d}")
        self.assertEqual(order.customer_id, 1)
        self.assertEqual((order.order_status, order.payment_status), ("PENDING", "PENDING"))
        self.assertEqual((order.subtotal, order.shipping_fee, order.discount_amount, order.total_amount),
                         (Decimal("20.26"), Decimal("1.24"), Decimal("0"), Decimal("21.50")))
        item = db.session.scalar(sa.select(OrderItem))
        self.assertEqual((item.product_name, item.sku, item.color_name, item.size_name, item.image),
                         ("Shoe", "BLACK-42", "Black", "42", "/uploads/products/a.png"))
        self.assertEqual((item.quantity, item.unit_price, item.subtotal), (2, Decimal("10.13"), Decimal("20.26")))
        payment = db.session.get(Payment, result["payment_id"])
        self.assertEqual((payment.payment_method, payment.payment_status, payment.amount), ("ONLINE", "PENDING", order.total_amount))
        self.assertIsNone(payment.qr_string)
        self.assertIsNone(payment.transaction_id)
        self.assertIsNone(payment.next_check_at)
        invoice = db.session.get(Invoice, result["invoice_id"])
        self.assertEqual(invoice.invoice_no, f"INV{invoice.id:05d}")
        self.assertEqual(invoice.total_amount, order.total_amount)
        history = db.session.scalar(sa.select(OrderStatusHistory))
        self.assertEqual((history.old_status, history.new_status, history.changed_by), (None, "PENDING", 1))
        movement = db.session.scalar(sa.select(StockMovement))
        self.assertEqual((movement.type, movement.qty_before, movement.qty_after, movement.qty_change), ("OUT", 5, 3, 2))
        self.assertEqual((movement.reference_type, movement.reference_id, movement.create_uid), ("ORDER", order.id, 1))
        self.assertEqual(db.session.get(VariantStock, 1).qty, 3)

    def test_insufficient_stock_and_duplicates_leave_no_writes(self):
        with self.assertRaises(BadRequestException):
            CheckoutService().checkout(1, self.payload(6))
        self.assert_no_checkout()
        data = self.payload()
        data["items"].append(dict(variant_stock_id=1, quantity=1))
        with self.assertRaises(BadRequestException):
            CheckoutService().checkout(1, data)
        self.assert_no_checkout()
        data["items"] = [dict(variant_stock_id=2, quantity=1), dict(variant_stock_id=1, quantity=6)]
        with self.assertRaises(BadRequestException):
            CheckoutService().checkout(1, data)
        self.assert_no_checkout()

    def test_invalid_delivery_accounts_and_catalog(self):
        mutations = [
            (DeliveryMethod, "is_active", False), (DeliveryMethod, "is_deleted", True),
            (DeliveryMethod, "currency", "KHR"), (Product, "is_active", False),
            (Product, "is_deleted", True), (Variant, "is_active", False),
            (VariantStock, "is_deleted", True), (ProductUnit, "multiplier", Decimal("2")),
            (ProductUnit, "is_deleted", True), (Unit, "is_active", False),
            (User, "status", "INACTIVE"), (User, "is_deleted", True),
            (Role, "is_active", False),
        ]
        for model, field, invalid in mutations:
            with self.subTest(model=model.__name__, field=field):
                entity = db.session.get(model, 1)
                original = getattr(entity, field)
                setattr(entity, field, invalid)
                db.session.commit()
                with self.assertRaises((BadRequestException, UnauthorizedException)):
                    CheckoutService().checkout(1, self.payload())
                self.assert_no_checkout()
                setattr(db.session.get(model, 1), field, original)
                db.session.commit()
        data = self.payload()
        data["delivery_method_id"] = 999
        with self.assertRaises(BadRequestException):
            CheckoutService().checkout(1, data)
        for identity in (None, True, 999):
            with self.assertRaises(UnauthorizedException):
                CheckoutService().checkout(identity, self.payload())
        self.assert_no_checkout()

    def test_client_fields_cod_and_bad_quantities_rejected(self):
        for field, value in (("total_amount", "0.01"), ("subtotal", "0.01"),
                             ("customer_id", 2), ("payment_method", "COD")):
            data = self.payload()
            data[field] = value
            with self.assertRaises(ValidationError):
                CheckoutService().checkout(1, data)
        for quantity in (0, -1, True, 1.5):
            with self.assertRaises(ValidationError):
                CheckoutService().checkout(1, self.payload(quantity))
        self.assert_no_checkout()

    def test_failure_after_stock_deduction_rolls_back_everything(self):
        for attribute in ("payments", "invoices", "histories"):
            with self.subTest(failing=attribute):
                service = CheckoutService()
                def fail(*args, **kwargs):
                    self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
                    self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement)), 1)
                    raise RuntimeError("injected creation failure")
                with patch.object(getattr(service, attribute), "create", side_effect=fail):
                    with self.assertRaisesRegex(RuntimeError, "injected"):
                        service.checkout(1, self.payload())
                self.assert_no_checkout()

    def test_inventory_caller_owned_mode_and_standalone_apis(self):
        inventory = VariantStockService()
        with patch.object(db.session, "commit", wraps=db.session.commit) as commit, patch.object(db.session, "rollback", wraps=db.session.rollback) as rollback:
            inventory.change_order_stock({1: 2}, False, 1, "ORD-test", commit=False)
            self.assertEqual(db.session.get(VariantStock, 1).qty, 3)
            self.assertEqual(commit.call_count, 0)
            self.assertEqual(rollback.call_count, 0)
        db.session.rollback()
        self.assert_no_checkout()
        with patch.object(db.session, "rollback", wraps=db.session.rollback) as rollback:
            with self.assertRaises(BadRequestException):
                inventory.change_order_stock({1: 6}, False, 1, "ORD-test", commit=False)
            self.assertEqual(rollback.call_count, 0)
        db.session.rollback()
        inventory.increase_stock(1, 2, 1)
        inventory.deduct_stock(1, 1, 1)
        inventory.set_stock_quantity(1, 8, 1)
        inventory.change_order_stock({1: 2}, False, 1, "ORD-test")
        self.assertEqual(db.session.get(VariantStock, 1).qty, 6)
        db.session.remove()
        self.assertEqual(db.session.get(VariantStock, 1).qty, 6)
        self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(StockMovement)), 4)

    def test_database_constraint_failure_rolls_back_checkout(self):
        service = CheckoutService()
        create = service.payments.create
        def invalid_payment(payment):
            payment.amount = Decimal("-1")
            return create(payment)  # Exercise a real PostgreSQL CHECK failure.
        with patch.object(service.payments, "create", side_effect=invalid_payment):
            with self.assertRaises(DuplicateException):
                service.checkout(1, self.payload())
        self.assert_no_checkout()

    def _concurrent(self, quantity):
        barrier = Barrier(2)
        def worker():
            with self.app.app_context():
                # Cache the original quantity in both sessions to exercise
                # populate_existing after one request waits on the row lock.
                cached_stock = db.session.get(VariantStock, 1)
                self.assertEqual(cached_stock.qty, 5)
                pid = db.session.scalar(sa.text("SELECT pg_backend_pid()"))
                service = CheckoutService()
                original = service.inventory.lock_order_stocks
                first = True
                def synchronize(*args, **kwargs):
                    nonlocal first
                    if first:
                        first = False
                        barrier.wait(timeout=10)
                    return original(*args, **kwargs)
                try:
                    with patch.object(service.inventory, "lock_order_stocks", side_effect=synchronize):
                        return pid, service.checkout(1, self.payload(quantity))
                except BadRequestException as exc:
                    return pid, str(exc)
                finally:
                    db.session.remove()
        db.session.remove()
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(lambda _: worker(), range(2)))
        self.assertNotEqual(results[0][0], results[1][0])
        return [result for pid, result in results]

    def test_concurrent_checkouts_cannot_oversell(self):
        results = self._concurrent(3)
        self.assertEqual(sum(isinstance(result, dict) for result in results), 1)
        self.assertIn("Insufficient stock", results)
        self.assertEqual(db.session.get(VariantStock, 1).qty, 2)
        for model in (Order, OrderItem, Payment, Invoice, OrderStatusHistory, StockMovement):
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(model)), 1)

    def test_concurrent_success_uses_unique_codes_and_correct_balances(self):
        results = self._concurrent(2)
        self.assertTrue(all(isinstance(result, dict) for result in results))
        self.assertEqual(len({result["order_code"] for result in results}), 2)
        self.assertEqual(len({result["invoice_no"] for result in results}), 2)
        self.assertEqual(db.session.get(VariantStock, 1).qty, 1)
        movements = db.session.scalars(sa.select(StockMovement).order_by(StockMovement.id)).all()
        self.assertEqual([(row.qty_before, row.qty_after) for row in movements], [(5, 3), (3, 1)])


if __name__ == "__main__":
    unittest.main()
