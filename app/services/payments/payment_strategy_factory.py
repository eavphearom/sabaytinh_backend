from flask import current_app

from app.enums.payment_method import PaymentMethod
from app.exceptions.api_exception import BadRequestException
from app.services.payments.payway_client import PayWayClient
from app.services.payments.payway_payment_strategy import PayWayPaymentStrategy


class PaymentStrategyFactory:
    @staticmethod
    def resolve(method):
        if method != PaymentMethod.ONLINE.value:
            raise BadRequestException("Only ONLINE payments are enabled")
        client = PayWayClient(current_app.config)
        client.ensure_configured()
        return PayWayPaymentStrategy(client)
