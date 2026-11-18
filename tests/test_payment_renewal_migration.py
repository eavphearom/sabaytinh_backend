import importlib.util
import os
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.extensions import db
from tests import test_payment_service as payment_tests


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class RenewalMigrationTests(unittest.TestCase):
    setUpClass = classmethod(payment_tests.PaymentServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(payment_tests.PaymentServicePostgresTests.tearDownClass.__func__)
    setUp = payment_tests.PaymentServicePostgresTests.setUp
    tearDown = payment_tests.PaymentServicePostgresTests.tearDown
    payload = payment_tests.PaymentServicePostgresTests.payload

    def test_upgrade_downgrade_preserve_existing_payments(self):
        path = Path(__file__).resolve().parents[1] / "migrations/versions/d42e9f01a673_payment_renewal_evidence.py"
        spec = importlib.util.spec_from_file_location("renewal_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "b73d1a0e9c42")
        db.session.remove()
        # Only this fixture's disposable schema, with transactional DDL rollback.
        with db.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": self.schema})
                before = connection.execute(text("SELECT id, amount, payment_status FROM payments")).all()
                with Operations.context(MigrationContext.configure(connection)):
                    migration.downgrade()
                    migration.upgrade()
                    self.assertEqual(connection.execute(text("SELECT id, amount, payment_status FROM payments")).all(), before)
                    self.assertEqual(tuple(connection.execute(text("SELECT replaces_payment_id, close_accepted_at, closure_verified_at FROM payments")).one()), (None, None, None))
                    constraints = connection.execute(text("SELECT constraint_name FROM information_schema.table_constraints WHERE table_schema=:schema AND table_name='payments'"), {"schema": self.schema}).scalars().all()
                    self.assertIn("uq_payments_replaces", constraints)
                    self.assertIn("fk_payments_replaces", constraints)
                    migration.downgrade()
                    self.assertEqual(connection.execute(text("SELECT id, amount, payment_status FROM payments")).all(), before)
            finally:
                transaction.rollback()
