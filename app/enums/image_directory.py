
from enum import Enum


class ImageDirectory(str, Enum):
    CATEGORY = "categories"
    BANNER = "banners"
    BRAND = "brands"
    PRODUCT = "products"
    PROFILE = "profiles"
    DELIVERY = "delivery"
