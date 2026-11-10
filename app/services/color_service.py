
from app.extensions import db
from app.models.color import Color
from app.repositories.color_repository import ColorRepository
from app.schemas.color_schema import ColorResponseSchema
from app.exceptions.api_exception import (
    BadRequestException,
    ResourceNotFoundException,
)
from app.utils.date_util import DateUtil


class ColorService:

    def __init__(self):
        self.repository = ColorRepository()
        self.schema = ColorResponseSchema()

    # Get paginated colors
    def get_paginated(self, filters):
        result = self.repository.find_paginated(filters)

        return {
            **result,
            "items": self.schema.dump(result["items"], many=True)
        }

    # Get color by ID
    def get_by_id(self, color_id):
        color = self.repository.find_by_id(color_id)

        if color is None:
            raise ResourceNotFoundException("Color not found")

        return self.schema.dump(color)

    # Create color
    def create(self, data, user_id):
        data = data.copy()
        data["name"] = data["name"].strip()

        if not data["name"]:
            raise BadRequestException("Name is required")

        if data.get("hex_code") is not None:
            data["hex_code"] = data["hex_code"].strip()

        try:
            color = Color(
                **data,
                created_at=DateUtil.now(),
                create_uid=user_id,
            )

            db.session.add(color)
            db.session.flush()

            result = self.schema.dump(color)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()
            raise

    # Update color
    def update(self, color_id, data, user_id):
        color = self.repository.find_by_id(color_id)

        if color is None:
            raise ResourceNotFoundException("Color not found")

        data = data.copy()

        if "name" in data:
            data["name"] = data["name"].strip()

            if not data["name"]:
                raise BadRequestException("Name is required")

        if data.get("hex_code") is not None:
            data["hex_code"] = data["hex_code"].strip()

        try:
            # Update provided fields only
            for field, value in data.items():
                setattr(color, field, value)

            color.updated_at = DateUtil.now()
            color.update_uid = user_id

            db.session.flush()

            result = self.schema.dump(color)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()
            raise

    # Soft delete color
    def delete(self, color_id, user_id):
        try:
            deleted = self.repository.soft_delete_by_id(
                color_id,
                deleted_uid=user_id
            )

            if not deleted:
                raise ResourceNotFoundException("Color not found")

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
