
from decimal import Decimal

from sqlalchemy import select

from app.extensions import db
from app.models.unit import Unit
from app.utils.date_util import DateUtil


class UnitSeeder:

    @staticmethod
    def seed():
        # Check whether PAIR already exists.
        unit = db.session.scalar(
            select(Unit).where(Unit.code == "PAIR")
        )

        if unit is not None:
            return False

        try:
            unit = Unit(
                code="PAIR",
                name="Pair",
                multiplier=Decimal("1.00000"),
                is_active=True,
                created_at=DateUtil.now()
            )

            db.session.add(unit)
            db.session.commit()

            return True

        except Exception:
            db.session.rollback()
            raise
