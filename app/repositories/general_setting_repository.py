from app.common.base_repository import BaseRepository
from app.extensions import db


class GeneralSettingRepository(BaseRepository):
    """Read-only lookups for internally selected setting entity models."""

    def find_active_options(self):
        return db.session.scalars(self._query().where(self.model.is_active.is_(True))
            .order_by(self.model.name.asc(), self.model.id.asc())).all()
