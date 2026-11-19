from flask import Blueprint, g, request

from app.common.api_response import ApiResponse
from app.common.filters import BaseFilter
from app.routes.v1.order_route_util import json_payload, paginated
from app.schemas.order_schema import OrderCancelRequestSchema
from app.security.decorators import customer_required
from app.services.order_service import OrderService
from app.services.invoice_service import InvoiceService


web_order_bp = Blueprint("web_orders", __name__, url_prefix="/api/v1/web")


@web_order_bp.after_request
def no_store(response):
    response.headers["Cache-Control"] = "no-store"
    return response


@web_order_bp.post("/checkout")
@customer_required
def checkout():
    order, initialized = OrderService().checkout(g.customer_id, json_payload())
    if not initialized:
        return ApiResponse.error(data=order, http_status=503, status="Service Unavailable",
            message="Order created; payment initialization pending. Check this order instead of submitting checkout again.")
    return ApiResponse.success(data=order, message="Order created", http_status=201)


@web_order_bp.get("/orders")
@customer_required
def history():
    return paginated(OrderService().get_customer_history(
        g.customer_id, BaseFilter.from_request(), request.args.to_dict()))


@web_order_bp.get("/orders/account-overview")
@customer_required
def account_overview():
    return ApiResponse.success(data=OrderService().get_account_overview(g.customer_id))


@web_order_bp.get("/orders/<int:order_id>")
@customer_required
def detail(order_id):
    return ApiResponse.success(data=OrderService().get_detail(order_id, g.customer_id))


@web_order_bp.get("/orders/<int:order_id>/invoice")
@customer_required
def invoice_detail(order_id):
    return ApiResponse.success(data=InvoiceService().get_customer_invoice(order_id, g.customer_id))


@web_order_bp.get("/orders/<int:order_id>/invoice/pdf")
@customer_required
def invoice_pdf(order_id):
    from flask import send_file
    from io import BytesIO
    from app.services.invoice_pdf_service import render_invoice_pdf
    data = InvoiceService().get_customer_invoice(order_id, g.customer_id)
    return send_file(BytesIO(render_invoice_pdf(data)), mimetype="application/pdf",
                     as_attachment=True, download_name=f"invoice-{data['id']}.pdf", max_age=0)


@web_order_bp.get("/orders/<int:order_id>/invoice/document")
@customer_required
def invoice_document(order_id):
    """JSON transport avoids download-manager interception of authenticated XHR."""
    import base64
    from app.services.invoice_pdf_service import render_invoice_pdf
    data = InvoiceService().get_customer_invoice(order_id, g.customer_id)
    return ApiResponse.success(data={
        "content_type": "application/pdf",
        "content_base64": base64.b64encode(render_invoice_pdf(data)).decode("ascii"),
    })


@web_order_bp.patch("/orders/<int:order_id>/cancel")
@customer_required
def cancel(order_id):
    data = OrderCancelRequestSchema().load(json_payload(
        allow_empty=True, example='{"reason": "Changed my mind"}'))
    return ApiResponse.success(data=OrderService().cancel(order_id, g.customer_id, data["reason"]),
                               message="Order cancelled")


@web_order_bp.route(
    "/orders/<int:order_id>/payment/check",
    methods=["GET", "POST"]
)
@customer_required
def check_payment(order_id):
    return ApiResponse.success(
        data=OrderService().check_payment(order_id, g.customer_id)
    )


@web_order_bp.post("/orders/<int:order_id>/payment/resume")
@customer_required
def resume_payment(order_id):
    return ApiResponse.success(data=OrderService().resume_payment(order_id, g.customer_id))
