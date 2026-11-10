from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from app.exceptions.api_exception import PaymentGatewayUnavailableException


class GatewayError(PaymentGatewayUnavailableException):
    """Sanitized error: never contains raw gateway bodies or credentials."""


@dataclass(frozen=True)
class PaymentContext:
    payment_id: int
    order_id: int
    transaction_id: str
    merchant_id: str
    amount: Decimal
    currency: str
    lease_token: str


@dataclass(frozen=True)
class GatewayResult:
    """Internal evidence from a trusted strategy, never a callback/request DTO."""
    transaction_id: str
    merchant_id: str
    amount: Decimal
    currency: str
    status: str  # READY, APPROVED, PENDING, CANCELLED, DECLINED, CLOSED
    reference: str | None = None
    qr_string: str | None = None
    qr_image: str | None = None
    abapay_deeplink: str | None = None
    expires_at: datetime | None = None


class PaymentStrategy(ABC):
    @abstractmethod
    def initialize(self, context):
        pass

    @abstractmethod
    def verify(self, context):
        pass

    @abstractmethod
    def close(self, context):
        pass
