from sqlalchemy import func, select

from app.common.base_repository import BaseRepository
from app.extensions import db
from app.models.order_item import OrderItem


class OrderItemRepository(BaseRepository):
    def __init__(self):
        super().__init__(OrderItem)

    def find_by_order_id(self, order_id):
        return db.session.scalars(
            self._query().where(OrderItem.order_id == order_id).order_by(OrderItem.id)
        ).all()

    def find_by_order_ids(self, order_ids):
        ids = list(dict.fromkeys(order_ids))
        if not ids:
            return []
        return db.session.scalars(
            self._query().where(OrderItem.order_id.in_(ids))
            .order_by(OrderItem.order_id, OrderItem.id)
        ).all()

    def sum_quantities_by_order_ids(self, order_ids):
        totals = dict.fromkeys(order_ids, 0)
        if totals:
            rows = db.session.execute(select(OrderItem.order_id, func.sum(OrderItem.quantity))
                .where(OrderItem.order_id.in_(totals), OrderItem.is_deleted.is_(False))
                .group_by(OrderItem.order_id)).all()
            totals.update({order_id: int(quantity) for order_id, quantity in rows})
        return totals

    def create(self, item):
        db.session.add(item)
        db.session.flush()
        return item

    def create_many(self, items):
        items = list(items)
        if items:
            db.session.add_all(items)
            db.session.flush()
        return items
