from enum import Enum


class PaymentMethod(str, Enum):
    COD = "COD"
    ONLINE = "ONLINE"

    @property
    def label(self):
        return {
            "COD": "Cash on Delivery",
            "ONLINE": "Online Payment"
        }[self.value]