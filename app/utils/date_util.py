
from datetime import datetime
from zoneinfo import ZoneInfo


class DateUtil:
    TIMEZONE = ZoneInfo("Asia/Phnom_Penh")

    @staticmethod
    def now():
        # Cambodia local time for PostgreSQL TIMESTAMP columns.
        return datetime.now(DateUtil.TIMEZONE).replace(tzinfo=None)

    @staticmethod
    def format(value):
        if value is None:
            return None

        return value.strftime("%Y-%m-%d %H:%M:%S")
