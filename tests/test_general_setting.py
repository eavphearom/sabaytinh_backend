from datetime import datetime, timedelta, timezone
from decimal import Decimal
import os
import unittest
from uuid import uuid4

from flask_jwt_extended import create_access_token
from sqlalchemy import event, select

from app.extensions import db, jwt
from app.exceptions.handlers import register_error_handlers
from app.models import Category, Brand, Color, Size, DeliveryMethod, Role, User, RefreshSession
from app.enums.order_status import OrderStatus
from app.enums.payment_status import PaymentStatus
from app.routes.v1.admin.general_setting_routes import admin_setting_bp
from app.routes.v1.web.general_setting_routes import web_setting_bp
from app.services.general_setting_service import GeneralSettingService
from app.security.jwt_utils import register_jwt_handlers
from tests import test_checkout_service as fixture


ADMIN_PATHS = ["form/product", "filter/product", "filter/stock-movement", "filter/order"]
WEB_PATHS = ["filter/shop", "form/order", "filter/order"]
MODELS = (Category, Brand, Color, Size, DeliveryMethod)


@unittest.skipUnless(os.getenv("CHECKOUT_TEST_DATABASE_URL"), "CHECKOUT_TEST_DATABASE_URL not set")
class GeneralSettingPostgresTests(unittest.TestCase):
    tearDownClass = classmethod(fixture.CheckoutServicePostgresTests.tearDownClass.__func__)
    tearDown = fixture.CheckoutServicePostgresTests.tearDown

    @classmethod
    def setUpClass(cls):
        fixture.CheckoutServicePostgresTests.setUpClass.__func__(cls)
        cls.app.config["JWT_SECRET_KEY"] = "general-setting-test-secret-not-for-real-use"
        jwt.init_app(cls.app)
        register_jwt_handlers(jwt)
        register_error_handlers(cls.app)
        cls.app.register_blueprint(admin_setting_bp)
        cls.app.register_blueprint(web_setting_bp)

    def setUp(self):
        fixture.CheckoutServicePostgresTests.setUp(self)
        for model in MODELS:
            for row in db.session.scalars(select(model)):
                row.name = "Zulu"
            for id in (11, 10, 12, 13):
                data = dict(id=id, name="Alpha", is_active=id != 12, is_deleted=id == 13)
                if model in (Category, Brand):
                    data["slug"] = f"setting-{id}"
                elif model == Size:
                    data["value"] = str(id)
                elif model == DeliveryMethod:
                    data.update(code=f"SETTING{id}", fee=Decimal("2.12345"), currency="KHR")
                db.session.add(model(**data))
        db.session.add(Role(id=2, name="Admin", code="ADMIN"))
        db.session.flush()
        db.session.add(User(id=2, username="Admin", email="admin@test.invalid", password="test", role_id=2))
        db.session.flush()
        self.headers = {}
        self.session_ids = {}
        for id in (1, 2):
            sid = uuid4()
            self.session_ids[id] = sid
            db.session.add(RefreshSession(id=sid, user_id=id, token_hash="test", revoked=False,
                                          expires_at=datetime.now(timezone.utc) + timedelta(hours=1)))
            self.headers[id] = {"Authorization": "Bearer " + create_access_token(
                identity=str(id), additional_claims={"sid": str(sid)})}
        db.session.commit()
        self.client = self.app.test_client()

    def admin(self, path, user=2):
        return self.client.get("/api/v1/admin/setting/" + path,
                               headers=self.headers[user] if user else {})

    def web(self, path):
        return self.client.get("/api/v1/web/setting/" + path)

    def test_product_form_filters_sorts_and_projects_all_entities(self):
        response = self.admin("form/product")
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json["error"])
        data = response.json["data"]
        self.assertEqual(set(data), {"categories", "brands", "colors", "sizes"})
        for key, options in data.items():
            self.assertEqual([x["id"] for x in options], [10, 11, 1, 2] if key == "sizes" else [10, 11, 1])
            self.assertEqual(set(options[0]), {"id", "name", "value"} if key == "sizes" else {"id", "name"})
        self.assertEqual(data["sizes"][0]["value"], "10")

    def test_admin_product_and_public_shop_filters_share_contract(self):
        admin = self.admin("filter/product")
        web = self.web("filter/shop")
        self.assertEqual((admin.status_code, web.status_code), (200, 200))
        self.assertEqual(admin.json, web.json)
        self.assertEqual(set(web.json["data"]), {"categories", "brands"})
        self.assertEqual([x["id"] for x in web.json["data"]["brands"]], [10, 11, 1])

    def test_stock_movement_enum_values(self):
        response = self.admin("filter/stock-movement")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json["data"], {"types": [
            {"value": "IN", "label": "In"}, {"value": "OUT", "label": "Out"}]})

    def test_correct_order_and_payment_enums_and_exact_keys(self):
        response = self.admin("filter/order")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(set(data), {"payment_statuses", "order_statuses"})
        self.assertEqual(data["payment_statuses"], [{"value": e.value, "label": e.label} for e in PaymentStatus])
        self.assertEqual(data["order_statuses"], [{"value": e.value, "label": e.label} for e in OrderStatus])
        web = self.web("filter/order")
        self.assertEqual(web.status_code, 200)
        self.assertEqual(web.json["data"], {"order_status": data["order_statuses"]})
        self.assertNotIn("CONFIRMED", str(web.json))

    def test_order_form_delivery_projection_and_online_only(self):
        response = self.web("form/order")
        self.assertEqual(response.status_code, 200)
        data = response.json["data"]
        self.assertEqual(set(data), {"deliveries", "payment-methods"})
        self.assertEqual(data["payment-methods"], [{"value": "ONLINE", "label": "Online Payment"}])
        self.assertEqual([x["id"] for x in data["deliveries"]], [10, 11, 1])
        self.assertEqual(data["deliveries"][0], {"id": 10, "name": "Alpha", "fee": 2.12345, "currency": "KHR"})
        self.assertIsInstance(data["deliveries"][0]["fee"], (int, float))

    def test_empty_entity_results_preserve_enums(self):
        for model in MODELS:
            for row in db.session.scalars(select(model)):
                row.is_active = False
        db.session.commit()
        self.assertEqual(self.admin("form/product").json["data"], dict(categories=[], brands=[], colors=[], sizes=[]))
        self.assertEqual(self.admin("filter/product").json["data"], dict(categories=[], brands=[]))
        self.assertEqual(self.web("filter/shop").json["data"], dict(categories=[], brands=[]))
        data = self.web("form/order").json["data"]
        self.assertEqual(data["deliveries"], [])
        self.assertEqual(len(data["payment-methods"]), 1)

    def test_all_admin_routes_require_admin_and_web_routes_are_public(self):
        for path in ADMIN_PATHS:
            with self.subTest(path=path):
                self.assertEqual(self.admin(path, user=None).status_code, 401)
                self.assertEqual(self.admin(path, user=1).status_code, 403)
                self.assertEqual(self.admin(path).status_code, 200)
        for path in WEB_PATHS:
            self.assertEqual(self.web(path).status_code, 200)

    def test_revoked_admin_session_is_rejected(self):
        db.session.get(RefreshSession, self.session_ids[2]).revoked = True
        db.session.commit()
        for path in ADMIN_PATHS:
            self.assertEqual(self.admin(path).status_code, 401)

    def test_inactive_admin_role_is_rejected(self):
        db.session.get(Role, 2).is_active = False
        db.session.commit()
        self.assertEqual(self.admin("form/product").status_code, 403)

    def test_no_duplicate_lookup_queries(self):
        calls = []
        def count(*args):
            calls.append(1)
        event.listen(db.engine, "before_cursor_execute", count)
        try:
            service = GeneralSettingService()
            service.product_form()
            self.assertEqual(len(calls), 4)
            calls.clear()
            service.product_filters()
            self.assertEqual(len(calls), 2)
            calls.clear()
            service.order_form()
            self.assertEqual(len(calls), 1)
            calls.clear()
            service.admin_order_filters()
            service.web_order_filters()
            service.stock_movement_filters()
            self.assertEqual(len(calls), 0)
        finally:
            event.remove(db.engine, "before_cursor_execute", count)


class GeneralSettingRegistrationTests(unittest.TestCase):
    def test_factory_registers_exact_routes_once(self):
        from app import create_app
        app = create_app()
        for prefix, paths in (("admin", ADMIN_PATHS), ("web", WEB_PATHS)):
            for path in paths:
                self.assertEqual(sum(rule.rule == f"/api/v1/{prefix}/setting/{path}" and "GET" in rule.methods
                                     for rule in app.url_map.iter_rules()), 1)
