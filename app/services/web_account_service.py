from dataclasses import replace

from app.enums.order_status import OrderStatus
from app.exceptions.api_exception import BadRequestException
from app.repositories.order_repository import OrderRepository
from app.schemas.web_account_schema import WebAccountOverviewSchema, WebAccountOrderSchema


class WebAccountService:
    SORT_FIELDS = {"id": "id", "createdAt": "created_at", "total": "total_amount"}

    def overview(self, customer_id):
        return WebAccountOverviewSchema().dump(OrderRepository().get_account_overview(customer_id))

    def orders(self, customer_id, filters, status=None):
        if filters.sort_by not in self.SORT_FIELDS:
            raise BadRequestException("sort_by must be id, createdAt or total")
        if status is not None and status not in {member.value for member in OrderStatus}:
            raise BadRequestException("Invalid order status")
        if filters.include_deleted or (filters.page_no - 1) * filters.per_page > 9223372036854775807:
            raise BadRequestException("Invalid pagination filters")
        mapped_filters = replace(filters, sort_by=self.SORT_FIELDS[filters.sort_by])
        result = OrderRepository().find_customer_history(customer_id, mapped_filters,
            {"order_status": status}, account=True)
        rows = []
        for order in result["items"]:
            items = order.items  # Eager batch-loaded, non-deleted only.
            preview = min(items, key=lambda item: item.id, default=None)
            rows.append({"id": order.id, "order_code": order.order_code,
                "created_at": order.created_at, "total": order.total_amount,
                "order_status": order.order_status, "payment_status": order.payment_status,
                "total_items": len(items), "preview_item": preview})
        return {**result, "items": WebAccountOrderSchema(many=True).dump(rows)}
