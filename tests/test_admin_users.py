import os
import unittest
from datetime import datetime
from sqlalchemy import event
from app.extensions import db
from app.models import User, Role
from app.routes.v1.admin.user_routes import admin_user_bp
from tests import test_admin_customers as fixture


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class AdminUserTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.AdminCustomerTests.tearDownClass.__func__)
    tearDown = fixture.AdminCustomerTests.tearDown
    setUp = fixture.AdminCustomerTests.setUp
    add_order = fixture.AdminCustomerTests.add_order

    @classmethod
    def setUpClass(cls):
        fixture.AdminCustomerTests.setUpClass.__func__(cls)
        cls.app.register_blueprint(admin_user_bp)

    def get(self, query="", user=4):
        return self.client.get("/api/v1/admin/users" + query, headers=self.headers.get(user, {}))

    def test_pagination_and_exact_safe_fields(self):
        for id in range(1, 5):
            db.session.get(User, id).created_at = datetime(2026, 1, 1)
        db.session.commit()
        result = self.get("?page=2&size=2")
        self.assertEqual(result.status_code, 200)
        self.assertEqual(result.json["pagination"], dict(page_no=2, per_page=2, total=4, total_page=2))
        self.assertEqual([u["id"] for u in result.json["data"]], [2, 1])
        for row in result.json["data"]:
            self.assertEqual(set(row), {"id", "username", "email", "role", "is_active"})
        self.assertEqual(result.json, self.get("?page_no=2&per_page=2").json)
        self.assertEqual(result.headers["Cache-Control"], "no-store")

    def test_search_and_role(self):
        for term in ("oThEr", "OTHER@TEST.INVALID"):
            self.assertEqual([u["id"] for u in self.get("?search=" + term).json["data"]], [2])
        self.assertEqual([u["id"] for u in self.get("?role_id=2").json["data"]], [4])
        self.assertEqual(self.get("?role_id=1").json["pagination"]["total"], 3)
        self.assertEqual(self.get("?role_id=1&search=admin").json["data"], [])

    def test_empty_results(self):
        for query in ("?search=missing", "?page=99", "?search=%25", "?search=_"):
            self.assertEqual(self.get(query).json["data"], [])

    def test_invalid_parameters(self):
        for query in ("page=0", "size=0", "size=101", "page=x", "size=1.5", "role=SUPER_ADMIN",
                      "role_id=", "role_id=admin", "role_id=0", "role_id=-1", "role_id=1.5",
                      "role_id=999", "role_id=9223372036854775808", "role_id=1&role_id=2", "page=1&page_no=1", "size=2&per_page=2",
                      "page=1&page=2", "include_deleted=true", "page=999999999999999999999"):
            self.assertEqual(self.get("?" + query).status_code, 400, query)

    def test_authorization(self):
        self.assertEqual(self.get(user=0).status_code, 401)
        self.assertEqual(self.get(user=1).status_code, 403)
        self.assertEqual(self.get("?role_id=2", user=1).status_code, 403)

    def test_deleted_exclusion_and_status(self):
        db.session.get(User, 2).is_deleted = True
        db.session.get(User, 3).status = "INACTIVE"
        db.session.commit()
        data = self.get().json["data"]
        self.assertEqual(len(data), 3)
        self.assertNotIn(2, [u["id"] for u in data])
        self.assertFalse(next(u for u in data if u["id"] == 3)["is_active"])
        self.assertEqual(self.get("?search=Other").json["data"], [])

    def test_newest_creation_and_constant_query_count(self):
        db.session.get(User, 1).created_at = datetime(2099, 1, 1)
        db.session.commit()
        statements = []
        def record(*args): statements.append(args[2])
        event.listen(db.engine, "before_cursor_execute", record)
        try:
            response = self.get()
        finally:
            event.remove(db.engine, "before_cursor_execute", record)
        self.assertEqual(response.json["data"][0]["id"], 1)
        self.assertLessEqual(len(statements), 5)


    def test_deleted_role_rejected_and_filtered_pagination(self):
        result = self.get("?role_id=1&page=2&size=1").json
        self.assertEqual(result["pagination"]["total"], 3)
        self.assertEqual(len(result["data"]), 1)
        self.assertEqual(result["data"][0]["role"], "USER")
        db.session.get(Role, 1).is_deleted = True
        db.session.commit()
        self.assertEqual(self.get("?role_id=1").status_code, 400)
