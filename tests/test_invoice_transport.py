import base64
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app import create_app
from app.exceptions.api_exception import ResourceNotFoundException


class InvoiceTransportTests(unittest.TestCase):
    def test_json_document_cors_and_owner_context(self):
        app = create_app()
        user = SimpleNamespace(status="ACTIVE", role=SimpleNamespace(is_deleted=False, is_active=True))
        path = "/api/v1/web/orders/18/invoice/document"
        headers = {"Origin": "http://localhost:5173"}
        client = app.test_client()
        self.assertEqual(client.get(path, headers=headers).status_code, 401)
        with patch("flask_jwt_extended.view_decorators.verify_jwt_in_request"), patch(
                "app.security.decorators.get_jwt_identity", return_value="7"), patch(
                "app.security.decorators.authenticated_user", return_value=user), patch(
                "app.services.invoice_service.InvoiceService.get_customer_invoice", return_value={"id": 1}) as lookup, patch(
                "app.services.invoice_pdf_service.render_invoice_pdf", return_value=b"%PDF-1.7\n\x00\xff") as render:
            result = client.get(path, headers=headers)
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.mimetype, "application/json")
            self.assertEqual(result.headers["Access-Control-Allow-Origin"], headers["Origin"])
            self.assertEqual(result.headers["Cache-Control"], "no-store")
            self.assertNotIn("Content-Disposition", result.headers)
            self.assertEqual(base64.b64decode(result.json["data"]["content_base64"]), b"%PDF-1.7\n\x00\xff")
            lookup.assert_called_once_with(18, 7)
            lookup.side_effect = ResourceNotFoundException("Invoice not found")
            render.reset_mock()
            # Error rollback must not access a real configured database in this test.
            with patch("app.exceptions.handlers.db.session.rollback"):
                result = client.get(path, headers=headers)
            self.assertEqual(result.status_code, 404)
            self.assertEqual(result.headers["Access-Control-Allow-Origin"], headers["Origin"])
            render.assert_not_called()
