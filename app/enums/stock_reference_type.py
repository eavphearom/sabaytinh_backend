
from enum import Enum


class StockReferenceType(str, Enum):
    INITIAL_STOCK = "INITIAL_STOCK"
    MANUAL_ADJUSTMENT = "MANUAL_ADJUSTMENT"
    ORDER = "ORDER"
    ORDER_RETURN = "ORDER_RETURN"
