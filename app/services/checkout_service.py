"""Internal pending checkout only; not a public or payment-initialized checkout.

The caller supplies the authenticated identity, never a client-selected customer.
This service owns the transaction and must not be called with unrelated pending
writes. A future payment orchestrator must initialize the gateway separately.
"""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.enums.currency import Currency
from app.enums.order_status import OrderStatus
from app.enums.payment_method import PaymentMethod
from app.enums.payment_status import PaymentStatus
from app.exceptions.api_exception import (
    BadRequestException, DuplicateException, UnauthorizedException,
)
from app.extensions import db
from app.models import (
    Order, OrderItem, Payment, Invoice, OrderStatusHistory, User, Role,
    DeliveryMethod, Product, Variant, VariantStock, VariantImage, Color, Size,
)
from app.repositories.order_repository import OrderRepository
from app.repositories.order_item_repository import OrderItemRepository
from app.repositories.payment_repository import PaymentRepository
from app.repositories.invoice_repository import InvoiceRepository
from app.repositories.order_status_history_repository import OrderStatusHistoryRepository
from app.schemas.order_schema import CheckoutRequestSchema
from app.services.variant_stock_service import VariantStockService
from app.utils.date_util import DateUtil


class CheckoutService:
    def __init__(self):
        self.orders = OrderRepository()
        self.items = OrderItemRepository()
        self.payments = PaymentRepository()
        self.invoices = InvoiceRepository()
        self.histories = OrderStatusHistoryRepository()
        self.inventory = VariantStockService()

    @staticmethod
    def _money(value):
        try:
            amount = Decimal(value)
            if not amount.is_finite() or amount < 0:
                raise InvalidOperation
            amount = amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
            if amount > Decimal("9999999999.99"):
                raise InvalidOperation
            return amount
        except (InvalidOperation, ValueError, TypeError):
            raise BadRequestException("Invalid or out-of-range USD amount")

    def checkout(self, authenticated_user_id, payload):
        """Create pending records atomically and return internal identifiers.

        Existing read-only authentication queries may have started the session's
        transaction; use that transaction rather than opening a second session.
        A successful return does not mean that payment initialization succeeded.
        """
        if db.session.new or db.session.dirty or db.session.deleted:
            raise RuntimeError("Checkout requires a session without pending unrelated writes")
        try:
            data = CheckoutRequestSchema().load(payload)
            if (type(authenticated_user_id) is not int
                    or not 1 <= authenticated_user_id <= 9_223_372_036_854_775_807):
                raise UnauthorizedException("Authenticated customer required")
            customer = db.session.scalar(select(User).join(Role, User.role_id == Role.id).where(
                User.id == authenticated_user_id, User.is_deleted.is_(False),
                User.status == "ACTIVE", Role.is_deleted.is_(False), Role.is_active.is_(True),
            ).execution_options(populate_existing=True))
            if customer is None:
                raise UnauthorizedException("Customer account is unavailable")
            delivery = db.session.scalar(select(DeliveryMethod).where(
                DeliveryMethod.id == data["delivery_method_id"],
                DeliveryMethod.is_deleted.is_(False), DeliveryMethod.is_active.is_(True),
            ).execution_options(populate_existing=True))
            if delivery is None:
                raise BadRequestException("Delivery method is unavailable")
            if delivery.currency != Currency.USD.value:
                raise BadRequestException("ONLINE checkout requires USD delivery pricing")
            quantities = {}
            for item in data["items"]:
                stock_id = item["variant_stock_id"]
                if stock_id in quantities:
                    raise BadRequestException("Duplicate variant stock ID")
                quantities[stock_id] = item["quantity"]
            self.inventory.lock_order_stocks(quantities)

            # Read authoritative snapshot data after stock locks are held.
            rows = db.session.execute(select(VariantStock, Variant, Product, Color, Size)
                .join(Variant, Variant.id == VariantStock.variant_id)
                .join(Product, Product.id == Variant.product_id)
                .join(Color, Color.id == Variant.color_id)
                .join(Size, Size.id == VariantStock.size_id)
                .where(VariantStock.id.in_(sorted(quantities)))
                .order_by(VariantStock.id)
                .execution_options(populate_existing=True)).all()
            if len(rows) != len(quantities):
                raise BadRequestException("Incomplete product configuration")
            images = {}
            for image in db.session.scalars(select(VariantImage).where(
                VariantImage.variant_id.in_({row[1].id for row in rows}),
                VariantImage.is_deleted.is_(False),
            ).order_by(VariantImage.variant_id, VariantImage.is_primary.desc(), VariantImage.id)):
                images.setdefault(image.variant_id, image.image)
            snapshots = []
            for stock, variant, product, color, size in rows:
                if (product.is_deleted or not product.is_active
                        or variant.is_deleted or not variant.is_active
                        or color.is_deleted or not color.is_active
                        or size.is_deleted or not size.is_active):
                    raise BadRequestException("Selected product option is unavailable")
                price = self._money(variant.price)
                quantity = quantities[stock.id]
                snapshots.append(OrderItem(
                    product_id=product.id, variant_id=variant.id, variant_stock_id=stock.id,
                    product_code=product.code, product_name=product.name,
                    sku=stock.sku, color_name=color.name, size_name=size.value or size.name,
                    image=images.get(variant.id), quantity=quantity, unit_price=price,
                    subtotal=self._money(price * quantity), create_uid=customer.id,
                ))
            subtotal = self._money(sum((item.subtotal for item in snapshots), Decimal("0")))
            shipping_fee = self._money(delivery.fee)
            total = self._money(subtotal + shipping_fee)
            money = dict(subtotal=subtotal, shipping_fee=shipping_fee,
                         discount_amount=Decimal("0.00"), total_amount=total,
                         currency=Currency.USD.value)
            order = self.orders.create(Order(
                order_code=f"TMP-{uuid4().hex}", customer_id=customer.id,
                delivery_method_id=delivery.id, delivery_method_name=delivery.name,
                order_status=OrderStatus.PENDING.value, payment_status=PaymentStatus.PENDING.value,
                recipient_name=data["recipient_name"].strip(),
                recipient_phone=data["recipient_phone"].strip(),
                delivery_address=data["delivery_address"].strip(), note=data.get("note"),
                create_uid=customer.id, **money,
            ))
            order.order_code = f"ORD{order.id:05d}"
            for item in snapshots:
                item.order_id = order.id
            self.items.create_many(snapshots)
            self.inventory.change_order_stock(
                quantities, False, order.id, order.order_code, commit=False, user_id=customer.id,
            )
            payment = self.payments.create(Payment(
                order_id=order.id, payment_method=PaymentMethod.ONLINE.value,
                payment_status=PaymentStatus.PENDING.value, amount=total,
                currency=Currency.USD.value, create_uid=customer.id,
            ))
            invoice = self.invoices.create(Invoice(
                order_id=order.id, invoice_no=f"TMP-{uuid4().hex}",
                payment_status=PaymentStatus.PENDING.value, issued_at=DateUtil.now(),
                create_uid=customer.id, **money,
            ))
            invoice.invoice_no = f"INV{invoice.id:05d}"
            self.histories.create(OrderStatusHistory(
                order_id=order.id, old_status=None, new_status=OrderStatus.PENDING.value,
                note="Order created", changed_at=DateUtil.now(), changed_by=customer.id,
                create_uid=customer.id,
            ))
            result = {"order_id": order.id, "order_code": order.order_code,
                      "payment_id": payment.id, "invoice_id": invoice.id,
                      "invoice_no": invoice.invoice_no}
            db.session.commit()
            return result
        except IntegrityError as exc:
            db.session.rollback()
            raise DuplicateException("Checkout conflicts with existing database records") from exc
        except Exception:
            db.session.rollback()
            raise
