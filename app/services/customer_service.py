from sqlalchemy.exc import OperationalError

from app.extensions import db
from app.exceptions.api_exception import BadRequestException, ResourceNotFoundException, ForbiddenException, DuplicateException
from app.repositories.customer_repository import CustomerRepository
from app.schemas.customer_schema import CustomerListSchema, CustomerDetailSchema
from app.services.order_service import OrderService


class CustomerService:
    def __init__(self):
        self.customers = CustomerRepository()

    def get_paginated(self, filters):
        if (filters.page_no - 1) * filters.per_page > 9_223_372_036_854_775_807:
            raise BadRequestException("Pagination offset is too large")
        rows, total = self.customers.list_customers(filters)
        return dict(items=CustomerListSchema(many=True).dump(rows), total=total,
            per_page=filters.per_page, page_no=filters.page_no,
            total_page=(total + filters.per_page - 1) // filters.per_page)

    def get_detail(self, customer_id):
        OrderService._validate_id(customer_id)
        customer = self.customers.detail(customer_id)
        if customer is None:
            raise ResourceNotFoundException("Customer not found")
        return CustomerDetailSchema().dump(customer)

    def delete(self, customer_id, actor_id):
        OrderService._validate_id(customer_id)
        try:
            self.customers.lock_customer_deletion()
            user = self.customers.find_by_id(customer_id)
            if user is None or self.customers.detail(customer_id) is None:
                raise ResourceNotFoundException("Customer not found")
            if user.role.code == "ADMIN":
                raise ForbiddenException("ADMIN accounts cannot be deleted")
            for order in self.customers.lock_orders(customer_id):
                if order.order_status not in ("DELIVERED", "CANCELLED"):
                    raise BadRequestException("Customer has unresolved orders")
                payment, invoice = OrderService._financial_records(order)
                if (payment.gateway_lease_token or payment.gateway_lease_until
                        or payment.next_check_at or payment.gateway_state not in ("PAID", "CLOSED")):
                    raise BadRequestException("Resolve payment operations and notifications before deletion")
                if order.order_status == "DELIVERED":
                    OrderService._require_verified_paid(order, payment, invoice)
                elif (payment.payment_status != "CANCELLED" or payment.gateway_state != "CLOSED"
                        or invoice.payment_status != "CANCELLED" or order.payment_status != "CANCELLED"):
                    raise BadRequestException("Cancellation payment state is unresolved")
            self.customers.soft_delete_by_id(customer_id, deleted_uid=actor_id,
                reason="Admin customer deletion")
            self.customers.revoke_sessions(customer_id)
            db.session.commit()
        except OperationalError as exc:
            db.session.rollback()
            if getattr(exc.orig, "pgcode", None) in ("55P03", "40P01") or getattr(exc.orig, "sqlstate", None) in ("55P03", "40P01"):
                raise DuplicateException("Customer activity is in progress; retry deletion later") from None
            raise
        except Exception:
            db.session.rollback()
            raise
