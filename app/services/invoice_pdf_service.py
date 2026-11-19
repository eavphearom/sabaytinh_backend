"""In-memory invoice PDFs; no remote resources, payment calls or database writes."""
from io import BytesIO
from pathlib import Path
from threading import Lock
import re
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, KeepTogether


_font_lock = Lock()


def _fonts():
    with _font_lock:
        if "Invoice" not in pdfmetrics.getRegisteredFontNames():
            root = Path(__file__).resolve().parents[1] / "assets" / "fonts"
            pdfmetrics.registerFont(TTFont("Invoice", str(root / "NotoSans-Regular.ttf"), shapable=True))
            pdfmetrics.registerFont(TTFont("InvoiceBold", str(root / "NotoSans-Bold.ttf"), shapable=True))
            pdfmetrics.registerFont(TTFont("InvoiceKhmer", str(root / "NotoSansKhmer-Regular.ttf"), shapable=True))
            pdfmetrics.registerFontFamily("Invoice", normal="Invoice", bold="InvoiceBold")


def render_invoice_pdf(data):
    _fonts()
    ink, muted, orange = colors.HexColor("#10243A"), colors.HexColor("#64748B"), colors.HexColor("#E96400")
    body = ParagraphStyle("body", fontName="Invoice", fontSize=10, leading=17, textColor=ink, shaping=1)
    title = ParagraphStyle("title", parent=body, fontName="InvoiceBold", fontSize=28, leading=36)
    small = ParagraphStyle("small", parent=body, fontSize=9, leading=15, textColor=muted)
    right = ParagraphStyle("right", parent=body, alignment=2)
    bold = ParagraphStyle("bold", parent=body, fontName="InvoiceBold")

    def p(value, style=body):
        # Paragraph treats markup as XML; escape all stored customer/catalog text.
        text = escape(str(value if value is not None else "—")).replace("\n", "<br/>")
        text = re.sub(r"[\u1780-\u17ff\u19e0-\u19ff\u200c\u200d]+",
                      lambda match: '<font name="InvoiceKhmer">' + match.group() + '</font>', text)
        return Paragraph(text, style)

    currency = data["currency"]
    money = lambda value: f"{currency} {value}"
    out = BytesIO()
    doc = SimpleDocTemplate(out, pagesize=A4, rightMargin=40, leftMargin=40,
                            topMargin=42, bottomMargin=48, title="Invoice", author="Go Shoes")
    width = A4[0] - 80
    header = Table([[p("GO SHOES", bold), p("INVOICE", title)],
                    [p("Order invoice", small), p(data["invoice_no"], right)]], colWidths=[width * .5] * 2)
    header.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LINEBELOW", (0, -1), (-1, -1), 2, orange),
                               ("BOTTOMPADDING", (0, -1), (-1, -1), 18)]))
    story = [header, Spacer(1, 20)]
    info = Table([
        [p("BILL TO / DELIVER TO", small), p("INVOICE DETAILS", small)],
        [p(data["recipient_name"], bold), p("Order: " + data["order_code"])],
        [p(data["recipient_phone"]), p("Issued: " + (data.get("issued_at") or "—"))],
        [p(data["delivery_address"]), p("Payment: " + data["payment_status"])],
        [p(data["delivery_method_name"], small), p("Paid at: " + (data.get("paid_at") or "—"), small)],
    ], colWidths=[width * .54, width * .46])
    info.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("BOTTOMPADDING", (0, 0), (-1, -1), 4)]))
    story += [info, Spacer(1, 24)]
    rows = [[p("ITEM", bold), p("QTY", bold), p("UNIT PRICE", bold), p("AMOUNT", bold)]]
    for item in data["items"]:
        description = [p(item["product_name"], bold), p(" / ".join(str(item.get(key) or "—") for key in ("color_name", "size_name", "sku")), small)]
        rows.append([description, p(item["quantity"], right), p(money(item["unit_price"]), right), p(money(item["subtotal"]), right)])
    if len(rows) == 1:
        rows.append([p("No available item records", small), "", "", ""])
    table = Table(rows, colWidths=[width * .44, width * .08, width * .24, width * .24], repeatRows=1, hAlign="LEFT")
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#FFF3E8")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 10), ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
        ("LINEBELOW", (0, 0), (-1, -1), .4, colors.HexColor("#E5EAF0")),
    ]))
    story += [table, Spacer(1, 18)]
    totals = Table([[p(label, bold if key == "total_amount" else body), p(money(data[key]), right)]
        for label, key in (("Subtotal", "subtotal"), ("Delivery", "shipping_fee"),
                           ("Discount", "discount_amount"), ("TOTAL", "total_amount"))],
        colWidths=[150, 150], hAlign="RIGHT")
    totals.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#FFF3E8")),
        ("LINEABOVE", (0, -1), (-1, -1), 1, orange)]))
    story.append(KeepTogether([totals, Spacer(1, 18), p("Thank you for shopping with Go Shoes.", small),
        p("This invoice reflects the recorded payment status. An unpaid invoice is not proof of payment.", small)]))

    def footer(canvas, document):
        canvas.setFont("Invoice", 8)
        canvas.setFillColor(muted)
        canvas.drawString(40, 25, "GO SHOES • INVOICE")
        canvas.drawRightString(A4[0] - 40, 25, f"Page {document.page}")

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return out.getvalue()
