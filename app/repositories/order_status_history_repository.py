from app.common.base_repository import BaseRepository
from app.extensions import db
from app.models.order_status_history import OrderStatusHistory


class OrderStatusHistoryRepository(BaseRepository):
    def __init__(self):
        super().__init__(OrderStatusHistory)

    def find_by_order_id(self, order_id):
        return db.session.scalars(self._query().where(OrderStatusHistory.order_id == order_id)
            .order_by(OrderStatusHistory.changed_at, OrderStatusHistory.id)).all()

    def create(self, history):
        db.session.add(history)
        db.session.flush()
        return history
