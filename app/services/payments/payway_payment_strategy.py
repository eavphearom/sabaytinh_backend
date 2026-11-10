from app.services.payments.payment_strategy import PaymentStrategy


class PayWayPaymentStrategy(PaymentStrategy):
    def __init__(self, client):
        self.client = client

    def initialize(self, context):
        return self.client.initialize(context)

    def verify(self, context):
        return self.client.verify(context)

    def close(self, context):
        return self.client.close(context)
