from sqlalchemy import select, func
from app.extensions import db
from app.models import Order, User, Product, Variant, VariantStock
from app.repositories.customer_repository import CustomerRepository


class DashboardRepository:
    @staticmethod
    def monthly_columns(timestamp, current_start, previous_start, now, amount=None):
        aggregate = func.sum(amount) if amount is not None else func.count()
        return [func.coalesce(aggregate, 0).label("value"),
            func.coalesce(aggregate.filter(timestamp >= current_start, timestamp <= now), 0).label("current_month"),
            func.coalesce(aggregate.filter(timestamp >= previous_start, timestamp < current_start), 0).label("previous_month")]

    def overview(self, current_start, previous_start, now):
        verified = CustomerRepository.verified_orders_query().subquery()
        revenue = db.session.execute(select(verified.c.currency, *self.monthly_columns(
            verified.c.paid_at, current_start, previous_start, now, verified.c.total_amount
        )).group_by(verified.c.currency)).mappings().all()
        orders = db.session.execute(select(*self.monthly_columns(
            Order.created_at, current_start, previous_start, now
        )).where(Order.is_deleted.is_(False))).mappings().one()
        first_orders = select(Order.customer_id, func.min(Order.created_at).label("first_order_at")).join(
            User, User.id == Order.customer_id).where(
                Order.is_deleted.is_(False), User.is_deleted.is_(False)
            ).group_by(Order.customer_id).subquery()
        customers = db.session.execute(select(*self.monthly_columns(
            first_orders.c.first_order_at, current_start, previous_start, now
        )).select_from(first_orders)).mappings().one()
        inventory = db.session.execute(select(
            func.count().filter(VariantStock.qty > 0, VariantStock.qty <= VariantStock.low_stock_alert).label("value"),
            func.count().filter(VariantStock.qty == 0).label("out_of_stock")
        ).select_from(VariantStock).join(Variant, Variant.id == VariantStock.variant_id)
            .join(Product, Product.id == Variant.product_id).where(
                VariantStock.is_deleted.is_(False), Variant.is_deleted.is_(False), Variant.is_active.is_(True),
                Product.is_deleted.is_(False), Product.is_active.is_(True)
            )).mappings().one()
        return revenue, orders, customers, inventory
