from app.enums.order_status import OrderStatus
from app.enums.payment_status import PaymentStatus
from app.enums.payment_method import PaymentMethod
from app.enums.stock_movement_type import StockMovementType
from app.models import Category, Brand, Color, Size, DeliveryMethod
from app.repositories.general_setting_repository import GeneralSettingRepository
from app.schemas.general_setting_schema import SettingOptionSchema, SettingSizeSchema, SettingDeliverySchema


class GeneralSettingService:
    """Shared Admin/Web lookup contracts; no writes or payment operations."""

    @staticmethod
    def _options(model, schema=None):
        schema = schema or SettingOptionSchema()
        return schema.dump(GeneralSettingRepository(model).find_active_options(), many=True)

    @staticmethod
    def _enum_options(members):
        return [{"value": member.value,
                 "label": getattr(member, "label", member.value.replace("_", " ").title())}
                for member in members]

    def product_filters(self):
        return {"categories": self._options(Category), "brands": self._options(Brand)}

    def product_form(self):
        return {**self.product_filters(), "colors": self._options(Color),
                "sizes": self._options(Size, SettingSizeSchema())}

    def stock_movement_filters(self):
        return {"types": self._enum_options(StockMovementType)}

    def admin_order_filters(self):
        return {"payment_statuses": self._enum_options(PaymentStatus),
                "order_statuses": self._enum_options(OrderStatus)}

    def order_form(self):
        return {"deliveries": self._options(DeliveryMethod, SettingDeliverySchema()),
                "payment-methods": self._enum_options([PaymentMethod.ONLINE])}

    def web_order_filters(self):
        return {"order_status": self._enum_options(OrderStatus)}
