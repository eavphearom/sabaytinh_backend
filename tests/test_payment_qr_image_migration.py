import importlib.util
import os
from pathlib import Path
import unittest

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import text

from app.config import Config
from app.extensions import db
from tests import test_payment_service as payment_tests


class QRImageLoggingTests(unittest.TestCase):
    def test_sql_parameters_are_hidden(self):
        from app import create_app
        with create_app().app_context():
            self.assertTrue(db.engine.hide_parameters)
        self.assertTrue(Config.SQLALCHEMY_ENGINE_OPTIONS["hide_parameters"])


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class QRImageMigrationTests(unittest.TestCase):
    setUpClass = classmethod(payment_tests.PaymentServicePostgresTests.setUpClass.__func__)
    tearDownClass = classmethod(payment_tests.PaymentServicePostgresTests.tearDownClass.__func__)
    setUp = payment_tests.PaymentServicePostgresTests.setUp
    tearDown = payment_tests.PaymentServicePostgresTests.tearDown
    payload = payment_tests.PaymentServicePostgresTests.payload

    def test_upgrade_preserves_existing_payment_and_downgrade_removes_only_image(self):
        path = Path(__file__).resolve().parents[1] / "migrations/versions/b73d1a0e9c42_persist_payment_qr_image.py"
        spec = importlib.util.spec_from_file_location("qr_image_migration", path)
        migration = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(migration)
        self.assertEqual(migration.down_revision, "800ccaedef30")
        db.session.remove()
        # DDL is confined to the test fixture's disposable schema and rolled back.
        with db.engine.connect() as connection:
            transaction = connection.begin()
            try:
                connection.execute(text("SELECT set_config('search_path', :schema, true)"), {"schema": self.schema})
                before = connection.execute(text("SELECT id, amount, payment_status FROM payments")).all()
                with Operations.context(MigrationContext.configure(connection)):
                    Operations(MigrationContext.configure(connection)).drop_column("payments", "qr_image")
                    migration.upgrade()
                    self.assertEqual(connection.execute(text("SELECT id, amount, payment_status FROM payments")).all(), before)
                    self.assertIsNone(connection.execute(text("SELECT qr_image FROM payments")).scalar_one())
                    connection.execute(text("UPDATE payments SET qr_image = :image"),
                                       {"image": "data:image/png;base64,dGVzdA=="})
                    self.assertEqual(connection.execute(text("SELECT qr_image FROM payments")).scalar_one(),
                                     "data:image/png;base64,dGVzdA==")
                    migration.downgrade()
                    self.assertEqual(connection.execute(text("SELECT id, amount, payment_status FROM payments")).all(), before)
                    exists = connection.execute(text("SELECT 1 FROM information_schema.columns WHERE table_schema=:schema AND table_name='payments' AND column_name='qr_image'"), {"schema": self.schema}).scalar()
                    self.assertIsNone(exists)
            finally:
                transaction.rollback()
