from datetime import date, datetime, time, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import selectinload

from app.common.base_repository import BaseRepository
from app.common.pagination import PaginationUtil
from app.enums.order_status import OrderStatus
from app.enums.payment_status import PaymentStatus
from app.exceptions.api_exception import BadRequestException
from app.extensions import db
from app.models.order import Order
from app.models.order_item import OrderItem
from app.models.payment import Payment
from app.models.invoice import Invoice
from app.models.order_status_history import OrderStatusHistory
from app.models.user import User
from app.models.delivery_method import DeliveryMethod


class OrderRepository(BaseRepository):
    def __init__(self):
        super().__init__(Order)

    def _loaded_query(self, include_deleted=False, detail=True):
        options = [
            selectinload(Order.customer.and_(User.is_deleted.is_(False))),
            selectinload(Order.items.and_(OrderItem.is_deleted.is_(False))),
            selectinload(Order.payments.and_(Payment.is_deleted.is_(False))),
        ]
        if detail:
            options.extend([
                selectinload(Order.delivery_method.and_(DeliveryMethod.is_deleted.is_(False))),
                selectinload(Order.invoice.and_(Invoice.is_deleted.is_(False))),
                selectinload(Order.status_histories.and_(OrderStatusHistory.is_deleted.is_(False))),
            ])
        # Refresh already-loaded relationships so deleted children cannot leak
        # from a previous unfiltered load in the same transaction.
        return self._query(include_deleted).options(*options).execution_options(
            populate_existing=True
        )

    def find_by_id(self, id, include_deleted=False):
        return db.session.scalar(self._loaded_query(include_deleted).where(Order.id == id))

    def find_by_id_for_update(self, order_id):
        """Lock only the order row, refreshing any cached state after waiting."""
        return db.session.scalar(
            self._query().where(Order.id == order_id)
            .with_for_update(of=Order).execution_options(populate_existing=True)
        )

    def find_by_id_and_customer_id(self, order_id, customer_id, for_update=False):
        query = self._query() if for_update else self._loaded_query()
        query = query.where(Order.id == order_id, Order.customer_id == customer_id)
        if for_update:
            query = query.with_for_update(of=Order).execution_options(populate_existing=True)
        return db.session.scalar(query)

    def find_by_code(self, order_code):
        return db.session.scalar(self._loaded_query().where(Order.order_code == order_code))

    @staticmethod
    def _date_boundary(value, end=False):
        """Date-only end bounds include that entire day; datetimes are exclusive."""
        if value is None or value == "":
            return None
        try:
            if isinstance(value, str):
                value = date.fromisoformat(value) if len(value) == 10 else datetime.fromisoformat(value)
            if isinstance(value, datetime):
                if value.tzinfo is not None:
                    raise ValueError("Expected local timestamp")
                return value
            if isinstance(value, date):
                if end:
                    value += timedelta(days=1)
                return datetime.combine(value, time.min)
        except (ValueError, OverflowError):
            pass
        raise BadRequestException("Dates must be local ISO dates or timestamps")

    def _filtered_query(self, filters, params, customer_id=None, account=False):
        if filters.page_no < 1 or not 1 <= filters.per_page <= 100:
            raise BadRequestException("Invalid pagination parameters")
        if filters.sort_dir not in ("asc", "desc"):
            raise BadRequestException("Invalid sort direction")
        # Customer queries always exclude deleted orders, regardless of flags.
        query = self._loaded_query(
            include_deleted=filters.include_deleted if customer_id is None else False,
            detail=False,
        )
        if account:
            # Account cards need only items; load all page items in one batch.
            query = self._query().options(selectinload(Order.items.and_(OrderItem.is_deleted.is_(False))))
            query = query.execution_options(populate_existing=True)
        if customer_id is not None:
            query = query.where(Order.customer_id == customer_id)
        elif params.get("customer_id") not in (None, ""):
            value = params["customer_id"]
            try:
                if (isinstance(value, bool) or not str(value).isdigit()
                        or not 1 <= int(value) <= 9_223_372_036_854_775_807):
                    raise ValueError
                query = query.where(Order.customer_id == int(value))
            except (TypeError, ValueError):
                raise BadRequestException("Invalid customer ID")
        for key, enum in (("order_status", OrderStatus), ("payment_status", PaymentStatus)):
            value = params.get(key)
            if value not in (None, ""):
                value = getattr(value, "value", value)
                if value not in [status.value for status in enum]:
                    raise BadRequestException(f"Invalid {key}")
                query = query.where(getattr(Order, key) == value)
        start = self._date_boundary(params.get("date_from"))
        end = self._date_boundary(params.get("date_to"), end=True)
        if start is not None and end is not None and start >= end:
            raise BadRequestException("date_from must precede the end of date_to")
        if start is not None:
            query = query.where(Order.created_at >= start)
        if end is not None:
            query = query.where(Order.created_at < end)
        if filters.search:
            keyword = filters.search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            pattern = f"%{keyword}%"
            if account:
                return query.where(Order.order_code.ilike(pattern, escape="\\"))
            query = query.where(or_(
                Order.order_code.ilike(pattern, escape="\\"),
                Order.recipient_name.ilike(pattern, escape="\\"),
                Order.recipient_phone.ilike(pattern, escape="\\"),
                Order.customer.has(User.is_deleted.is_(False) & User.username.ilike(pattern, escape="\\")),
            ))
        return query

    def find_paginated(self, filters, params=None):
        return PaginationUtil.paginate(
            self._filtered_query(filters, params or {}), Order, filters,
            {"id", "order_code", "created_at", "total_amount", "order_status", "payment_status"},
        )

    def find_customer_history(self, customer_id, filters, params=None, *, account=False):
        if type(customer_id) is not int or customer_id <= 0:
            raise BadRequestException("A customer ID is required")
        return PaginationUtil.paginate(
            self._filtered_query(filters, params or {}, customer_id=customer_id, account=account),
            Order, filters, {"id", "order_code", "created_at", "total_amount"},
        )

    def get_account_overview(self, customer_id):
        """In progress: PENDING/PROCESSING/SHIPPED; completed: DELIVERED."""
        row = db.session.execute(select(
            func.count(Order.id).label("total_orders"),
            func.count(Order.id).filter(Order.order_status.in_([
                OrderStatus.PENDING.value, OrderStatus.PROCESSING.value, OrderStatus.SHIPPED.value,
            ])).label("in_progress"),
            func.count(Order.id).filter(Order.order_status == OrderStatus.DELIVERED.value).label("completed"),
        ).where(Order.customer_id == customer_id, Order.is_deleted.is_(False))).mappings().one()
        return dict(row)

    def create(self, order):
        db.session.add(order)
        db.session.flush()
        return order

    # Soft deletion is inherited from BaseRepository and only flushes.
