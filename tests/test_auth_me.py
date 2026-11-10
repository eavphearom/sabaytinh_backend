import os
import unittest
from datetime import datetime
from app.extensions import db
from app.models import User
from app.routes.v1.auth import auth_bp
from tests import test_admin_customers as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class AuthMeTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.AdminCustomerTests.tearDownClass.__func__)
    tearDown = fixture.AdminCustomerTests.tearDown
    setUp = fixture.AdminCustomerTests.setUp
    add_order = fixture.AdminCustomerTests.add_order

    @classmethod
    def setUpClass(cls):
        fixture.AdminCustomerTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(auth_bp)

    def test_profile_fields_for_user_and_admin(self):
        for id, role in ((1, "USER"), (4, "ADMIN")):
            user = db.session.get(User, id)
            user.phone = "012345678"
            user.profile = "/uploads/profiles/photo.png"
            user.created_at = datetime(2026, 8, 12, 10, 30)
            db.session.commit()
            response = self.client.get("/api/v1/auth/me", headers=self.headers[id])
            self.assertEqual(response.status_code, 200)
            data = response.json["data"]
            self.assertEqual(set(data), {"id", "username", "email", "role", "is_active", "phone", "profile", "created_at"})
            self.assertEqual(data["id"], id)
            self.assertEqual(data["role"], role)
            self.assertTrue(data["is_active"])
            self.assertEqual(data["phone"], "012345678")
            self.assertEqual(data["created_at"], "2026-08-12T10:30:00")
            self.assertEqual(data["profile"], "http://localhost/uploads/profiles/photo.png")

    def test_null_fields_and_absolute_profile_url(self):
        user = db.session.get(User, 1)
        user.phone = user.profile = user.created_at = None
        db.session.commit()
        data = self.client.get("/api/v1/auth/me", headers=self.headers[1]).json["data"]
        for field in ("phone", "profile", "created_at"):
            self.assertIsNone(data[field])
        user.profile = "https://example.com/photo.png"
        db.session.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.headers[1]).json["data"]["profile"], user.profile)

    def test_auth_checks_unchanged(self):
        self.assertEqual(self.client.get("/api/v1/auth/me").status_code, 401)
        db.session.get(User, 1).status = "INACTIVE"
        db.session.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.headers[1]).status_code, 401)
        db.session.get(User, 2).is_deleted = True
        db.session.commit()
        self.assertEqual(self.client.get("/api/v1/auth/me", headers=self.headers[2]).status_code, 401)
