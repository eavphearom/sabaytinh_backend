"""Customer projections over existing users; no separate customer entity."""
from sqlalchemy import select, func, or_, update, text

from app.extensions import db
from app.models import User, Order, Payment, Invoice, RefreshSession
from app.repositories.user_repository import UserRepository


class CustomerRepository(UserRepository):
    @staticmethod
    def verified_orders_query():
        # Mirror OrderService's verified-paid predicate, with one financial set.
        payment_count = select(func.count(Payment.id)).where(
            Payment.order_id == Order.id).correlate(Order).scalar_subquery()
        verified = select(Payment.id).join(Invoice, Invoice.order_id == Payment.order_id).where(
            Payment.order_id == Order.id, Payment.is_deleted.is_(False),
            Invoice.is_deleted.is_(False), Payment.payment_method == "ONLINE",
            Payment.payment_status == "PAID", Invoice.payment_status == "PAID",
            Payment.gateway_state.in_(("PAID", "PAID_NOTIFY_PENDING")),
            Payment.transaction_id.is_not(None), Payment.transaction_id != "",
            Payment.payment_reference.is_not(None), Payment.payment_reference != "",
            Payment.paid_at.is_not(None), Invoice.paid_at.is_not(None),
            Payment.amount == Order.total_amount, Invoice.total_amount == Order.total_amount,
            Payment.currency == Order.currency, Invoice.currency == Order.currency,
        ).correlate(Order).exists()
        paid_at = select(Payment.paid_at).where(Payment.order_id == Order.id).correlate(Order).limit(1).scalar_subquery()
        return select(Order.id, Order.customer_id, Order.currency, Order.total_amount,
            paid_at.label("paid_at")).where(
                Order.is_deleted.is_(False), Order.order_status != "CANCELLED",
                Order.payment_status == "PAID", payment_count == 1, verified,
            )

    @staticmethod
    def spending_query():
        return CustomerRepository.verified_orders_query().with_only_columns(
            Order.customer_id, Order.currency, func.sum(Order.total_amount).label("amount")
        ).group_by(Order.customer_id, Order.currency)

    @staticmethod
    def query(search=""):
        stats = select(Order.customer_id, func.count(Order.id).label("total_orders"),
            func.max(Order.created_at).label("last_order_at")).where(
                Order.is_deleted.is_(False)).group_by(Order.customer_id).subquery()
        query = select(User.id, User.username, User.email, User.phone, User.profile,
            User.status, User.created_at, stats.c.total_orders, stats.c.last_order_at
        ).join(stats, stats.c.customer_id == User.id).where(User.is_deleted.is_(False))
        if search:
            escaped = search.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            query = query.where(or_(*(column.ilike(f"%{escaped}%", escape="\\")
                for column in (User.username, User.email, User.phone))))
        return query

    def list_customers(self, filters):
        query = self.query(filters.search)
        total = db.session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rows = db.session.execute(query.order_by(
            text("last_order_at DESC"), User.id.desc()
        ).offset((filters.page_no - 1) * filters.per_page).limit(filters.per_page)).mappings().all()
        return self.with_spending(rows), total

    def detail(self, customer_id):
        row = db.session.execute(self.query().where(User.id == customer_id)).mappings().first()
        return self.with_spending([row])[0] if row else None

    def with_spending(self, rows):
        if not rows:
            return []
        totals = {}
        for customer_id, currency, amount in db.session.execute(
                self.spending_query().where(Order.customer_id.in_([r["id"] for r in rows]))):
            totals.setdefault(customer_id, {})[getattr(currency, "value", currency)] = amount
        result = []
        for row in rows:
            item = dict(row)
            amounts = totals.get(row["id"], {})
            item["total_spent_by_currency"] = amounts
            item["total_spent"] = next(iter(amounts.values()), 0) if len(amounts) <= 1 else None
            item["currency"] = next(iter(amounts), None) if len(amounts) <= 1 else None
            result.append(item)
        return result

    @staticmethod
    def lock_customer_deletion():
        # Existing checkout retains ACCESS SHARE on users from its eligibility
        # read until commit. NOWAIT refuses concurrent reads/writes instead of
        # waiting or letting an already validated checkout insert after deletion.
        connection = db.session.connection()
        if connection.dialect.name != "postgresql":
            raise RuntimeError("Safe customer deletion requires PostgreSQL")
        schema = connection.get_execution_options().get("schema_translate_map", {}).get(None)
        preparer = connection.dialect.identifier_preparer
        table = (preparer.quote_schema(schema) + "." if schema else "") + preparer.quote("users")
        connection.execute(text(f"LOCK TABLE {table} IN ACCESS EXCLUSIVE MODE NOWAIT"))

    @staticmethod
    def lock_orders(customer_id):
        # Include deleted orders: hiding an order does not resolve its finances.
        return db.session.scalars(select(Order).where(Order.customer_id == customer_id)
            .order_by(Order.id).with_for_update().execution_options(populate_existing=True)).all()

    @staticmethod
    def revoke_sessions(customer_id):
        db.session.execute(update(RefreshSession).where(RefreshSession.user_id == customer_id)
            .values(revoked=True))
