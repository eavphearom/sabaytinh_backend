import unittest
from app.services.invoice_pdf_service import render_invoice_pdf


def sample_invoice(count=2):
    return dict(id=1, invoice_no="INV00019", order_code="ORD00019", currency="USD", payment_status="PAID",
        recipient_name="Sok Dara", recipient_phone="012345678", delivery_address="Street 271, Phnom Penh, Cambodia",
        delivery_method_name="Standard delivery", issued_at="2026-11-19 15:27:00", paid_at="2026-11-19 15:29:00",
        subtotal="46.00", shipping_fee="2.00", discount_amount="0.00", total_amount="48.00",
        items=[dict(id=i, product_name="Nike Air Max", color_name="Black", size_name="42", sku=f"NIKE-BLK-{i}",
                    quantity=1, unit_price="23.00", subtotal="23.00") for i in range(count)])


class InvoicePdfTests(unittest.TestCase):
    def test_pdf_header_long_items_and_escaped_text(self):
        data = sample_invoice(70)
        data["recipient_name"] = '<script>alert("test")</script> & Customer'
        data["delivery_address"] = "Long delivery address " * 25
        data["items"][0]["product_name"] = "Long product name <b>literal</b> & variant " * 8
        pdf = render_invoice_pdf(data)
        self.assertTrue(pdf.startswith(b"%PDF-"))
        self.assertTrue(pdf.rstrip().endswith(b"%%EOF"))

    def test_khmer_and_empty_items_render(self):
        data = sample_invoice(0)
        data["recipient_name"] = "សុខ ដារ៉ា"
        data["delivery_address"] = "ភ្នំពេញ កម្ពុជា"
        self.assertTrue(render_invoice_pdf(data).startswith(b"%PDF-"))
