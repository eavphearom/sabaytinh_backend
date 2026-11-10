from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP
from app.enums.currency import Currency
from app.repositories.dashboard_repository import DashboardRepository
from app.schemas.dashboard_schema import DashboardOverviewSchema
from app.utils.date_util import DateUtil


class DashboardService:
    @staticmethod
    def statistic(row):
        result = dict(row)
        previous = Decimal(result["previous_month"])
        result["percentage_change"] = (float(((Decimal(result["current_month"]) - previous) / previous * 100)
            .quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)) if previous else None)
        return result

    def overview(self):
        now = DateUtil.now()
        current_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        previous_start = (current_start - timedelta(days=1)).replace(day=1)
        revenue, orders, customers, inventory = DashboardRepository().overview(current_start, previous_start, now)
        by_currency = {getattr(row["currency"], "value", row["currency"]): row for row in revenue}
        revenue_rows = []
        for currency in Currency:
            row = dict(by_currency.get(currency.value, dict(value=0, current_month=0, previous_month=0)))
            row["currency"] = currency.value
            revenue_rows.append(self.statistic(row))
        return DashboardOverviewSchema().dump(dict(total_revenue=revenue_rows,
            orders=self.statistic(orders), customers=self.statistic(customers),
            low_stock={**inventory, "percentage_change": None}, metadata={
                "timezone": str(DateUtil.TIMEZONE), "as_of": now.isoformat(timespec="seconds"),
                "current_month_start": current_start.isoformat(),
                "previous_month_start": previous_start.isoformat(),
                "previous_month_end_exclusive": current_start.isoformat(),
                "comparison": "current_month_to_date_vs_previous_full_calendar_month",
                "value_scope": "cumulative_currently_eligible_records; low_stock_is_current_inventory",
                "revenue_timestamp": "payment.paid_at",
                "new_customer_basis": "earliest_non_deleted_order",
                "historical_limitation": "Monthly figures reflect current deletion/refund states, not immutable historical snapshots.",
                "low_stock_comparison": "unavailable_without_historical_inventory_snapshots",
            }))
