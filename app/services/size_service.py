
from app.extensions import db
from app.models.size import Size
from app.repositories.size_repository import SizeRepository
from app.schemas.size_schema import SizeResponseSchema
from app.exceptions.api_exception import ResourceNotFoundException
from app.utils.date_util import DateUtil


class SizeService:

    def __init__(self):
        self.repository = SizeRepository()
        self.schema = SizeResponseSchema()

    # Get paginated sizes
    def get_paginated(self, filters):
        result = self.repository.find_paginated(filters)

        return {
            **result,
            "items": self.schema.dump(result["items"], many=True)
        }

    # Get size by ID
    def get_by_id(self, size_id):
        size = self.repository.find_by_id(size_id)

        if size is None:
            raise ResourceNotFoundException("Size not found")

        return self.schema.dump(size)

    # Create size
    def create(self, data, user_id):
        data = self._clean_data(data)

        try:
            size = Size(
                **data,
                created_at=DateUtil.now(),
                create_uid=user_id
            )

            db.session.add(size)
            db.session.flush()

            result = self.schema.dump(size)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()
            raise

    # Update size
    def update(self, size_id, data, user_id):
        size = self.repository.find_by_id(size_id)

        if size is None:
            raise ResourceNotFoundException("Size not found")

        data = self._clean_data(data)

        try:
            # Update only fields provided by client.
            for field, value in data.items():
                setattr(size, field, value)

            size.updated_at = DateUtil.now()
            size.update_uid = user_id

            db.session.flush()

            result = self.schema.dump(size)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()
            raise

    # Soft delete size
    def delete(self, size_id, user_id):
        try:
            deleted = self.repository.soft_delete_by_id(
                size_id,
                deleted_uid=user_id
            )

            if not deleted:
                raise ResourceNotFoundException("Size not found")

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise

    @staticmethod
    def _clean_data(data):
        """Trim optional text fields."""
        data = data.copy()

        for field in (
            "name", "value", "size_system", "description"
        ):
            if field in data and data[field] is not None:
                data[field] = data[field].strip()

        return data
