
import logging

from app.extensions import db
from app.models.banner import Banner
from app.repositories.banner_repository import BannerRepository
from app.schemas.banner_schema import BannerResponseSchema
from app.exceptions.api_exception import (
    BadRequestException,
    ResourceNotFoundException,
)
from app.utils.file_util import FileUtil
from app.enums.image_directory import ImageDirectory
from app.utils.date_util import DateUtil


logger = logging.getLogger(__name__)


class BannerService:

    def __init__(self):
        self.repository = BannerRepository()
        self.schema = BannerResponseSchema()

    # Get paginated banners
    def get_paginated(self, filters):
        result = self.repository.find_paginated(filters)

        return {
            **result,
            "items": self.schema.dump(result["items"], many=True)
        }

    # Get banner by ID
    def get_by_id(self, banner_id):
        banner = self.repository.find_by_id(banner_id)

        if banner is None:
            raise ResourceNotFoundException("Banner not found")

        return self.schema.dump(banner)

    # Create banner
    def create(self, data, user_id, image_file=None):
        data = data.copy()

        title = data["title"].strip()

        if not title:
            raise BadRequestException("Title is required")

        if not image_file or not image_file.filename:
            raise BadRequestException("Banner image is required")

        data["title"] = title

        if data.get("subtitle") is not None:
            data["subtitle"] = data["subtitle"].strip()

        new_image = None

        try:
            # Upload banner image
            new_image = FileUtil.save_image(
                image_file,
                ImageDirectory.BANNER
            )

            banner = Banner(
                **{
                    **data,
                    "image": new_image,
                    "is_active": data.get("is_active", True)
                },
                created_at=DateUtil.now(),
                create_uid=user_id
            )

            db.session.add(banner)
            db.session.flush()

            result = self.schema.dump(banner)
            db.session.commit()

            return result

        except Exception:
            db.session.rollback()

            if new_image:
                try:
                    FileUtil.delete_image(new_image)
                except OSError:
                    logger.exception(
                        "Failed to clean up banner image"
                    )

            raise

    # Update banner
    def update(self, banner_id, data, user_id, image_file=None):
        banner = self.repository.find_by_id(banner_id)

        if banner is None:
            raise ResourceNotFoundException("Banner not found")

        data = data.copy()

        if "title" in data:
            data["title"] = data["title"].strip()

            if not data["title"]:
                raise BadRequestException("Title is required")

        if data.get("subtitle") is not None:
            data["subtitle"] = data["subtitle"].strip()

        old_image = banner.image
        new_image = None

        try:
            # Replace image only if a new file is uploaded
            if image_file:
                new_image = FileUtil.save_image(
                    image_file,
                    ImageDirectory.BANNER
                )
                data["image"] = new_image

            # Update provided fields only
            for field, value in data.items():
                setattr(banner, field, value)

            banner.updated_at = DateUtil.now()
            banner.update_uid = user_id

            db.session.flush()

            result = self.schema.dump(banner)
            db.session.commit()

        except Exception:
            db.session.rollback()

            if new_image:
                try:
                    FileUtil.delete_image(new_image)
                except OSError:
                    logger.exception(
                        "Failed to clean up new banner image"
                    )

            raise

        # Delete old image after successful commit
        if new_image and old_image != new_image:
            try:
                FileUtil.delete_image(old_image)
            except OSError:
                logger.exception(
                    "Failed to delete old banner image"
                )

        return result

    # Soft delete banner
    def delete(self, banner_id, user_id):
        try:
            deleted = self.repository.soft_delete_by_id(
                banner_id,
                deleted_uid=user_id
            )

            if not deleted:
                raise ResourceNotFoundException("Banner not found")

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
