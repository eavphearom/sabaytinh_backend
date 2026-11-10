"""Order DTO validation and serialization only.

Authentication, database existence checks, and state transitions belong to the
route/service layer. Aggregate response fields must be supplied by that layer;
these schemas do not calculate totals or select a payment for an order.
"""

from collections.abc import Mapping
from decimal import ROUND_HALF_UP

from marshmallow import (
    RAISE, Schema, ValidationError, fields, missing, post_dump, validate,
)

from app.enums.order_status import OrderStatus
from app.enums.payment_method import PaymentMethod
from app.enums.payment_status import PaymentStatus
from app.schemas.user_schema import CustomerResponseSchema
from app.utils.file_util import FileUtil


TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S"
MAX_ID = 9_223_372_036_854_775_807
MAX_QUANTITY = 2_147_483_647


def nonblank(value):
    if not value.strip():
        raise ValidationError("Must not be blank.")


class EnumValueField(fields.String):
    """Serialize both model enum members and DTO strings as their wire value."""

    def _serialize(self, value, attr, obj, **kwargs):
        return super()._serialize(getattr(value, "value", value), attr, obj, **kwargs)


class ImageURLField(fields.String):
    def _serialize(self, value, attr, obj, **kwargs):
        return FileUtil.get_image_url(value)


def money():
    return fields.Decimal(places=2, as_string=True, rounding=ROUND_HALF_UP)


def timestamp():
    return fields.DateTime(format=TIMESTAMP_FORMAT, allow_none=True)


class OrderRequestSchema(Schema):
    class Meta:
        unknown = RAISE


class CheckoutItemRequestSchema(OrderRequestSchema):
    variant_stock_id = fields.Integer(
        required=True, strict=True, validate=validate.Range(min=1, max=MAX_ID)
    )
    quantity = fields.Integer(
        required=True, strict=True,
        validate=validate.Range(min=1, max=MAX_QUANTITY),
    )


class CheckoutRequestSchema(OrderRequestSchema):
    delivery_method_id = fields.Integer(
        required=True, strict=True, validate=validate.Range(min=1, max=MAX_ID)
    )
    recipient_name = fields.String(
        required=True, validate=[nonblank, validate.Length(max=150)]
    )
    recipient_phone = fields.String(
        required=True, validate=[nonblank, validate.Length(max=30)]
    )
    delivery_address = fields.String(required=True, validate=nonblank)
    note = fields.String(allow_none=True, validate=validate.Length(max=255))
    payment_method = fields.String(
        required=True, validate=validate.OneOf([PaymentMethod.ONLINE.value])
    )
    items = fields.List(
        fields.Nested(CheckoutItemRequestSchema),
        required=True, validate=validate.Length(min=1),
    )


class OrderStatusUpdateRequestSchema(OrderRequestSchema):
    order_status = fields.String(
        required=True, validate=validate.OneOf([status.value for status in OrderStatus])
    )
    note = fields.String(allow_none=True, validate=validate.Length(max=255))


class PaymentStatusUpdateRequestSchema(OrderRequestSchema):
    # Contract supplied for Step 2: payment_status and optional note only.
    payment_status = fields.String(
        required=True, validate=validate.OneOf([status.value for status in PaymentStatus])
    )
    note = fields.String(allow_none=True, validate=validate.Length(max=255))


class OrderCancelRequestSchema(OrderRequestSchema):
    reason = fields.String(
        required=True, validate=[nonblank, validate.Length(max=255)]
    )


class OrderItemResponseSchema(Schema):
    id = fields.Integer()
    order_id = fields.Integer()
    product_id = fields.Integer()
    variant_id = fields.Integer()
    variant_stock_id = fields.Integer()
    product_code = fields.String(allow_none=True)
    product_name = fields.String()
    sku = fields.String()
    color_name = fields.String(allow_none=True)
    size_name = fields.String(allow_none=True)
    image = ImageURLField(allow_none=True)
    quantity = fields.Integer()
    unit_price = money()
    subtotal = money()


class PaymentResponseSchema(Schema):
    id = fields.Integer()
    order_id = fields.Integer()
    payment_method = EnumValueField()
    payment_status = EnumValueField()
    amount = money()
    currency = EnumValueField()
    transaction_id = fields.String(allow_none=True)
    payment_reference = fields.String(allow_none=True)
    note = fields.String(allow_none=True)
    paid_at = timestamp()
    qr_string = fields.String(allow_none=True)
    # Gateway QR content is passed through; it is not a local uploaded image.
    qr_image = fields.String(allow_none=True)
    abapay_deeplink = fields.String(allow_none=True)
    checkout_qr_url = fields.String(allow_none=True)
    expires_at = timestamp()
    checkout_status = fields.String(allow_none=True)
    checkout_message = fields.String(allow_none=True)

    @post_dump
    def omit_null_checkout_fields(self, data, **kwargs):
        for key in (
            "qr_string", "qr_image", "abapay_deeplink", "checkout_qr_url",
            "expires_at", "checkout_status", "checkout_message",
        ):
            if data.get(key) is None:
                data.pop(key, None)
        return data


class InvoiceResponseSchema(Schema):
    id = fields.Integer()
    order_id = fields.Integer()
    invoice_no = fields.String()
    subtotal = money()
    shipping_fee = money()
    discount_amount = money()
    total_amount = money()
    currency = EnumValueField()
    payment_status = EnumValueField()
    issued_at = timestamp()
    paid_at = timestamp()


class OrderStatusHistoryResponseSchema(Schema):
    id = fields.Integer()
    order_id = fields.Integer()
    old_status = EnumValueField(allow_none=True)
    new_status = EnumValueField()
    note = fields.String(allow_none=True)
    changed_at = timestamp()
    changed_by = fields.Integer(allow_none=True)


class OrderResponseSchema(Schema):
    id = fields.Integer()
    order_code = fields.String()
    customer_id = fields.Integer()
    delivery_method_id = fields.Integer()
    delivery_method_name = fields.String()
    order_status = EnumValueField()
    payment_status = EnumValueField()
    subtotal = money()
    shipping_fee = money()
    discount_amount = money()
    total_amount = money()
    currency = EnumValueField()
    recipient_name = fields.String()
    recipient_phone = fields.String()
    delivery_address = fields.String()
    note = fields.String(allow_none=True)
    cancelled_at = timestamp()
    delivered_at = timestamp()
    created_at = timestamp()
    customer = fields.Nested(CustomerResponseSchema, allow_none=True)
    items = fields.List(fields.Nested(OrderItemResponseSchema))
    payments = fields.List(fields.Nested(PaymentResponseSchema))
    invoice = fields.Nested(InvoiceResponseSchema, allow_none=True)
    status_history = fields.List(fields.Nested(OrderStatusHistoryResponseSchema))

    def get_attribute(self, obj, attr, default):
        if isinstance(obj, Mapping):
            # Avoid resolving a missing "items" key to dict.items().
            if attr == "status_history" and attr not in obj:
                return obj.get("status_histories", default)
            return obj.get(attr, default)
        value = super().get_attribute(obj, attr, missing)
        if attr == "status_history" and value is missing:
            return super().get_attribute(obj, "status_histories", default)
        return default if value is missing else value


class OrderPaginationResponseSchema(Schema):
    """One pagination row; the existing ApiResponse owns pagination metadata."""

    id = fields.Integer()
    order_code = fields.String()
    customer_id = fields.Integer()
    customer_name = fields.String()
    recipient_name = fields.String()
    recipient_phone = fields.String()
    delivery_address = fields.String()
    note = fields.String(allow_none=True)
    order_status = EnumValueField()
    payment_status = EnumValueField()
    payment_method = EnumValueField(allow_none=True)
    total_amount = money()
    currency = EnumValueField()
    total_items = fields.Integer()
    created_at = timestamp()


class OrderPreviewItemResponseSchema(Schema):
    product_name = fields.String()
    image = ImageURLField(allow_none=True)
    color = fields.String(allow_none=True)
    size = fields.String(allow_none=True)
    qty = fields.Integer()
    price = money()


class OrderHistoryResponseSchema(Schema):
    id = fields.Integer()
    order_code = fields.String()
    created_at = timestamp()
    total = money()
    order_status = EnumValueField()
    payment_status = EnumValueField()
    total_items = fields.Integer()
    preview_item = fields.Nested(OrderPreviewItemResponseSchema, allow_none=True)


class AccountOverviewResponseSchema(Schema):
    total_orders = fields.Integer()
    in_progress = fields.Integer()
    completed = fields.Integer()
