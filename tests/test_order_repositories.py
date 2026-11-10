"""Isolated query tests; PostgreSQL locks are compiled, not exercised by SQLite.

SQLite test tables copy column types only. PostgreSQL constraints and identity
behavior are outside this fixture; no configured application database is used.
"""
import ast
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
import unittest
from unittest.mock import patch

from flask import Flask
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.common.filters import BaseFilter
from app.exceptions.api_exception import BadRequestException
from app.extensions import db
from app.models import (
    Order, OrderItem, Payment, Invoice, OrderStatusHistory, User, DeliveryMethod,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.order_item_repository import OrderItemRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.order_status_history_repository import OrderStatusHistoryRepository


NOW = datetime(2026, 11, 10, 12)


class OrderRepositoryTests(unittest.TestCase):
    def setUp(self):
        app = Flask(__name__)
        app.config.update(SQLALCHEMY_DATABASE_URI="sqlite://", TESTING=True)
        db.init_app(app)
        self.context = app.app_context()
        self.context.push()
        metadata = sa.MetaData()
        for model in (Order, OrderItem, Payment, Invoice, OrderStatusHistory, User, DeliveryMethod):
            sa.Table(model.__tablename__, metadata, *[
                sa.Column(c.name, c.type, primary_key=c.primary_key, nullable=c.nullable)
                for c in model.__table__.columns
            ])
        metadata.create_all(db.engine)
        db.session.add_all([
            User(id=1, username="Dara", email="d@example.com", password="hash", role_id=1),
            User(id=2, username="Other", email="o@example.com", password="hash", role_id=1),
            DeliveryMethod(id=1, name="Delivery", code="DELIVERY", fee=Decimal("1")),
        ])
        self.repo = OrderRepository()

    def tearDown(self):
        db.session.remove()
        db.engine.dispose()
        self.context.pop()

    def order(self, id, **values):
        data = dict(id=id, order_code=f"ORD-{id}", customer_id=1,
                    delivery_method_id=1, delivery_method_name="Delivery",
                    recipient_name="Dara", recipient_phone="012345678",
                    delivery_address="Phnom Penh", created_at=NOW)
        data.update(values)
        entity = Order(**data)
        self.repo.create(entity)
        return entity

    def item(self, id, order_id, quantity=1, **values):
        entity = OrderItem(id=id, order_id=order_id, product_id=1, variant_id=1,
                           variant_stock_id=id, product_name="Shoe", sku=f"SKU-{id}",
                           quantity=quantity, unit_price=Decimal("2"),
                           subtotal=Decimal(2 * quantity), **values)
        return OrderItemRepository().create(entity)

    def payment(self, id, order_id, **values):
        data = dict(id=id, order_id=order_id, payment_method="ONLINE",
                    amount=Decimal("2"), created_at=NOW, next_check_at=NOW)
        data.update(values)
        return PaymentRepository().create(Payment(**data))

    def test_retrieval_customer_scope_and_soft_delete(self):
        order = self.order(1)
        self.order(2, customer_id=2)
        self.assertIs(self.repo.find_by_code("ORD-1"), order)
        self.assertIsNone(self.repo.find_by_id_and_customer_id(1, 2))
        self.assertIs(self.repo.find_by_id_and_customer_id(1, 1), order)
        self.assertTrue(self.repo.soft_delete_by_id(1, deleted_uid=1, reason="test"))
        self.assertIsNone(self.repo.find_by_id(1))
        self.assertIsNone(self.repo.find_by_code("ORD-1"))
        self.assertIs(self.repo.find_by_id(1, include_deleted=True), order)
        self.assertEqual(order.deleted_reason, "test")
        self.assertFalse(self.repo.soft_delete_by_id(999))
        self.assertEqual(self.repo.find_customer_history(1, BaseFilter(include_deleted=True))["total"], 0)
        for value in (None, 0, True, "1"):
            with self.assertRaises(BadRequestException):
                self.repo.find_customer_history(value, BaseFilter())

    def test_filters_search_dates_and_pagination(self):
        self.order(1, order_code="ORD-100%", order_status="PROCESSING", payment_status="PAID")
        self.order(2, order_code="ORD-100X", customer_id=2, created_at=NOW - timedelta(days=1))
        self.order(3, created_at=NOW + timedelta(days=1))
        self.assertEqual(self.repo.find_paginated(BaseFilter(search="100%"))["total"], 1)
        result = self.repo.find_paginated(BaseFilter(), {
            "customer_id": "1", "order_status": "PROCESSING", "payment_status": "PAID",
            "date_from": "2026-11-10", "date_to": "2026-11-10",
        })
        self.assertEqual([x.id for x in result["items"]], [1])
        result = self.repo.find_paginated(BaseFilter(per_page=1, page_no=2))
        self.assertEqual([x.id for x in result["items"]], [2])
        self.assertEqual((result["total"], result["total_page"]), (3, 3))
        result = self.repo.find_customer_history(1, BaseFilter(), {"customer_id": 2})
        self.assertEqual({x.id for x in result["items"]}, {1, 3})
        self.assertEqual(self.repo.find_paginated(BaseFilter(search="Other"))["total"], 1)
        for params in ({"order_status": "CONFIRMED"}, {"payment_status": "bad"},
                       {"customer_id": "1.2"}, {"date_to": "invalid"},
                       {"date_from": "2026-11-11", "date_to": "2026-11-10"}):
            with self.assertRaises(BadRequestException):
                self.repo.find_paginated(BaseFilter(), params)

    def test_overview_counts(self):
        for id, status in enumerate(("PENDING", "PROCESSING", "SHIPPED", "DELIVERED", "CANCELLED"), 1):
            self.order(id, order_status=status)
        self.order(6, is_deleted=True)
        self.order(7, customer_id=2)
        self.assertEqual(self.repo.get_account_overview(1), {
            "total_orders": 5, "in_progress": 3, "completed": 1,
        })
        self.assertEqual(self.repo.get_account_overview(99), {
            "total_orders": 0, "in_progress": 0, "completed": 0,
        })

    def test_item_batch_and_quantity_sum(self):
        self.order(1)
        self.order(2)
        self.item(1, 1, 3)
        self.item(2, 1, 5, is_deleted=True)
        self.item(3, 2, 2)
        repo = OrderItemRepository()
        self.assertEqual([x.id for x in repo.find_by_order_id(1)], [1])
        self.assertEqual([x.id for x in repo.find_by_order_ids([2, 1, 1])], [1, 3])
        self.assertEqual(repo.sum_quantities_by_order_ids([1, 2, 99]), {1: 3, 2: 2, 99: 0})
        self.assertEqual(repo.find_by_order_ids([]), [])
        self.assertEqual(repo.sum_quantities_by_order_ids([]), {})
        self.assertEqual(repo.create_many([]), [])

    def test_payment_latest_transaction_and_due_lease_filters(self):
        self.order(1)
        self.payment(1, 1, transaction_id="txn-1", expires_at=NOW - timedelta(minutes=1))
        self.payment(2, 1, gateway_lease_until=NOW + timedelta(minutes=1))
        self.payment(3, 1, gateway_lease_until=NOW)
        self.payment(4, 1, payment_status="PAID")
        self.payment(5, 1, payment_method="COD")
        self.payment(6, 1, next_check_at=NOW + timedelta(seconds=1))
        self.payment(7, 1, next_check_at=None)
        self.payment(8, 1, is_deleted=True, transaction_id="deleted")
        repo = PaymentRepository()
        self.assertEqual(repo.find_latest_by_order_id(1).id, 7)
        self.assertEqual(len(repo.find_by_order_id(1)), 7)
        self.assertEqual(repo.find_by_transaction_id("txn-1", for_update=True).id, 1)
        self.assertIsNone(repo.find_by_transaction_id(None))
        self.assertIsNone(repo.find_by_transaction_id("deleted"))
        self.assertEqual([x.id for x in repo.find_pending_online_for_reconciliation(NOW)], [1, 3])
        self.assertEqual([x.id for x in repo.find_pending_online_for_reconciliation(NOW, limit=1)], [1])
        for value in (None, "2026-11-10"):
            with self.assertRaises(ValueError):
                repo.find_pending_online_for_reconciliation(value)

    def test_invoice_and_chronological_history(self):
        self.order(1)
        repo = InvoiceRepository()
        invoice = repo.create(Invoice(id=1, order_id=1, invoice_no="INV-1", issued_at=NOW))
        self.assertIs(repo.find_by_order_id(1), invoice)
        self.assertIs(repo.find_by_invoice_no("INV-1"), invoice)
        invoice.payment_status = "PAID"
        repo.update(invoice)
        self.assertEqual(repo.find_by_order_id(1).payment_status, "PAID")
        history = OrderStatusHistoryRepository()
        for id, when, deleted in [(3, NOW, False), (2, NOW, False), (1, NOW - timedelta(days=1), False), (4, NOW, True)]:
            history.create(OrderStatusHistory(id=id, order_id=1, new_status="PENDING", changed_at=when, is_deleted=deleted))
        self.assertEqual([x.id for x in history.find_by_order_id(1)], [1, 2, 3])
        invoice.is_deleted = True
        repo.update(invoice)
        self.assertIsNone(repo.find_by_invoice_no("INV-1"))

    def test_eager_loading_filters_cached_children_and_bounds_queries(self):
        for id in range(1, 4):
            self.order(id)
            self.item(id, id)
            self.payment(id, id)
        self.item(4, 1, is_deleted=True)
        order = db.session.get(Order, 1)
        self.assertEqual(len(order.items), 2)  # Unfiltered ORM relationship.
        self.assertEqual(len(self.repo.find_by_id(1).items), 1)
        db.session.expire_all()
        statements = []
        def record(conn, cursor, statement, parameters, context, executemany):
            statements.append(statement)
        sa.event.listen(db.engine, "before_cursor_execute", record)
        try:
            result = self.repo.find_paginated(BaseFilter())
            count = len(statements)
            for row in result["items"]:
                _ = row.customer.username, len(row.items), len(row.payments)
            self.assertEqual(len(statements), count)
            self.assertEqual(count, 5)  # count + orders + three select-in batches
        finally:
            sa.event.remove(db.engine, "before_cursor_execute", record)

    def test_caller_rollback_undoes_flushed_writes(self):
        db.session.commit()  # Fixture only; repositories must never commit.
        self.order(1)
        self.item(1, 1)
        self.payment(1, 1)
        InvoiceRepository().create(Invoice(id=1, order_id=1, invoice_no="INV-1", issued_at=NOW))
        OrderStatusHistoryRepository().create(OrderStatusHistory(id=1, order_id=1, new_status="PENDING", changed_at=NOW))
        db.session.rollback()
        for model in (Order, OrderItem, Payment, Invoice, OrderStatusHistory):
            self.assertEqual(db.session.scalar(sa.select(sa.func.count()).select_from(model)), 0)

    def test_postgresql_lock_sql_and_transaction_boundaries(self):
        for method, args, target in [
            (self.repo.find_by_id_for_update, (1,), "orders"),
            (self.repo.find_by_id_and_customer_id, (1, 1, True), "orders"),
            (PaymentRepository().find_by_id_for_update, (1,), "payments"),
            (PaymentRepository().find_by_transaction_id, ("txn", True), "payments"),
        ]:
            with patch.object(db.session, "scalar") as mocked:
                method(*args)
                query = mocked.call_args.args[0]
                compiled = str(query.compile(dialect=postgresql.dialect()))
                self.assertIn(f"FOR UPDATE OF {target}", compiled)
                self.assertIn(f"{target}.is_deleted IS false", compiled)
                self.assertTrue(query.get_execution_options()["populate_existing"])
        with patch.object(db.session, "scalars") as mocked:
            PaymentRepository().find_pending_online_for_reconciliation(NOW)
            compiled = str(mocked.call_args.args[0].compile(dialect=postgresql.dialect()))
            self.assertIn("FOR UPDATE OF payments SKIP LOCKED", compiled)
        root = Path(__file__).resolve().parents[1] / "app" / "repositories"
        for name in ("order", "order_item", "payment", "invoice", "order_status_history"):
            tree = ast.parse((root / f"{name}_repository.py").read_text())
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                    self.assertNotIn(node.func.attr, {"commit", "rollback"})


if __name__ == "__main__":
    unittest.main()
