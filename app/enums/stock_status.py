from enum import Enum


class StockStatus(str, Enum):
    IN_STOCK = "IN_STOCK"
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"

    @staticmethod
    def from_quantity(qty, low_stock_alert):
        if qty is None or qty == 0:
            return StockStatus.OUT_OF_STOCK

        if low_stock_alert is not None and qty <= low_stock_alert:
            return StockStatus.LOW_STOCK

        return StockStatus.IN_STOCK