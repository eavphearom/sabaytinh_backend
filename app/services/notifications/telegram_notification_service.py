"""Telegram delivery for the payment service's committed, verified events."""
import html
import http.client
import json
import re
import ssl

from flask import current_app
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.extensions import db
from app.models import Order, OrderItem, Payment
from app.utils.date_util import DateUtil
from app.workers.execution_scope import external_timeouts, read_response


class NotificationDeliveryError(Exception):
    """Safe error message; never retain the request URL or Telegram body."""

    def __init__(self, message, retry_after=90):
        super().__init__(message)
        self.retry_after = retry_after


class TelegramNotificationService:
    @staticmethod
    def _text(value, limit=200):
        value = getattr(value, "value", value)
        text = " ".join(str(value or "").split())
        text = "".join(c for c in text if c.isprintable())
        if len(text) > limit:
            text = text[:limit - 1] + "…"
        return html.escape(text, quote=False)

    def notify_verified_payment(self, event):
        """Only called by the leased dispatcher, after its transaction commits."""
        if db.session().in_transaction():
            raise NotificationDeliveryError("Notification requires a committed transaction")
        text = self._snapshot(event)
        return self._send(text)

    def _snapshot(self, event):
        try:
            payment = db.session.scalar(select(Payment).where(
                Payment.id == event.get("payment_id"), Payment.is_deleted.is_(False)))
            if (payment is None or event.get("event_id") != f"payment:{payment.id}:paid"
                    or payment.order_id != event.get("order_id")
                    or payment.payment_method != "ONLINE" or payment.payment_status != "PAID"
                    or payment.gateway_state != "PAID_NOTIFY_PENDING"
                    or payment.paid_at is None or not payment.transaction_id
                    or not payment.gateway_lease_token or payment.gateway_lease_until is None
                    or payment.gateway_lease_until <= DateUtil.now()
                    or event.get("refund_review")):
                raise NotificationDeliveryError("Event is not a verified purchase notification")
            order = db.session.scalar(select(Order).where(
                Order.id == payment.order_id, Order.is_deleted.is_(False)
            ).options(selectinload(Order.customer), selectinload(
                Order.items.and_(OrderItem.is_deleted.is_(False)))))
            if order is None or order.order_status == "CANCELLED" or order.payment_status != "PAID":
                raise NotificationDeliveryError("Order is not eligible for a purchase notification")
            customer = order.customer
            name = customer.username if customer and not customer.is_deleted else order.recipient_name
            currency = getattr(order.currency, "value", order.currency)
            def money(amount):
                return f"${amount:.2f}" if currency == "USD" else f"{amount:.2f} {self._text(currency)}"

            lines = ["🛒 <b>PAYMENT RECEIVED</b>", "",
                     f"🧾 Order: #{self._text(order.order_code)}",
                     f"🕒 Order at: {DateUtil.format(order.created_at)}", "",
                     f"👤 Customer: {self._text(name)}",
                     f"📞 Phone: {self._text(order.recipient_phone)}", "", "📦 <b>Items:</b>"]
            for item in sorted(order.items, key=lambda item: item.id):
                lines.extend([
                    f"• {self._text(item.product_name, 255)}",
                    f"  👟 Size: {self._text(item.size_name) or '—'}",
                    f"  🎨 Color: {self._text(item.color_name) or '—'}",
                    f"  🔢 Qty: {item.quantity}",
                    f"  💵 Price: {money(item.unit_price)}", "",
                ])
            lines.extend([
                f"💳 Payment: {self._text(payment.payment_method.label)}",
                f"⏳ Payment Status: {self._text(payment.payment_status)}", "",
                f"🚚 Delivery: {self._text(order.delivery_method_name)}",
            ])
            # Escape each address line while retaining its original line breaks.
            address = (order.delivery_address or "").splitlines() or [""]
            lines.append("📍 Address: " + self._text(address[0], 500))
            lines.extend(self._text(line, 500) for line in address[1:])
            lines.extend(["", f"💰 Total: {money(order.total_amount)}",
                          f"📋 Order Status: {self._text(order.order_status)}",
                          f"Event: {event['event_id']}"])
            return "\n".join(lines)
        finally:
            db.session.rollback()  # No database transaction during HTTPS.

    @staticmethod
    def _message_parts(text):
        # Split on complete HTML lines so tags/entities are never cut. Each
        # formatted field is bounded above; conservative UTF-16 sizing includes tags.
        parts = []
        lines = []
        for line in text.split("\n"):
            if len(line.encode("utf-16-le")) // 2 > 3900:
                raise NotificationDeliveryError("Notification line exceeds message limit")
            candidate = "\n".join(lines + [line])
            if len(candidate.encode("utf-16-le")) // 2 > 3900:
                parts.append("\n".join(lines))
                lines = []
            lines.append(line)
        if lines:
            parts.append("\n".join(lines))
        return parts

    def _send(self, text):
        # The existing event is acknowledged only after every part succeeds.
        # A retry after partial delivery may repeat parts (at-least-once delivery).
        message_id = None
        for part in self._message_parts(text):
            message_id = self._send_message(part)
        return message_id

    def _send_message(self, text):
        token = current_app.config.get("TELEGRAM_BOT_TOKEN") or ""
        chat = str(current_app.config.get("TELEGRAM_CHAT_ID") or "").strip()
        if not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token) or not chat:
            raise NotificationDeliveryError("Telegram credentials are missing or invalid")
        payload = json.dumps({"chat_id": chat, "text": text, "parse_mode": "HTML",
                              "link_preview_options": {"is_disabled": True}}, ensure_ascii=False).encode("utf-8")
        connection = None
        try:
            # Fixed HTTPS host, no redirects, no request/response logging.
            connect_timeout, read_timeout = external_timeouts(5, 15)
            connection = http.client.HTTPSConnection("api.telegram.org", timeout=connect_timeout,
                                                     context=ssl.create_default_context())
            connection.connect()
            connection.sock.settimeout(read_timeout)
            connection.request("POST", f"/bot{token}/sendMessage", body=payload,
                               headers={"Content-Type": "application/json"})
            response = connection.getresponse()
            raw = read_response(response, connection, 65537, read_timeout)
            if len(raw) > 65536:
                raise NotificationDeliveryError("Telegram response is invalid")
            data = json.loads(raw)
            if not isinstance(data, dict):
                raise NotificationDeliveryError("Telegram response is invalid")
            if response.status == 429 or data.get("error_code") == 429:
                parameters = data.get("parameters")
                delay = parameters.get("retry_after") if isinstance(parameters, dict) else None
                if type(delay) is not int or not 0 < delay <= 604800:
                    delay = 604800  # Invalid rate-limit evidence: fail conservatively.
                raise NotificationDeliveryError("Telegram rate limited", retry_after=max(90, delay))
            result = data.get("result")
            if (response.status != 200 or data.get("ok") is not True
                    or not isinstance(result, dict) or type(result.get("message_id")) is not int):
                raise NotificationDeliveryError("Telegram rejected the message")
            return result["message_id"]
        except NotificationDeliveryError:
            raise
        except (OSError, http.client.HTTPException, ValueError):
            raise NotificationDeliveryError("Telegram delivery unavailable or uncertain") from None
        finally:
            if connection is not None:
                connection.close()

    def retry_pending(self, limit=100):
        """Explicit operator/worker entry point; no scheduler is installed."""
        from app.services.payments.payment_state_service import PaymentStateService
        return PaymentStateService(paid_hook=self.notify_verified_payment).dispatch_pending_notifications(limit)
