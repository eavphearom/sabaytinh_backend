from enum import Enum


class StockMovementType(str, Enum):
    IN = "IN"
    OUT = "OUT"