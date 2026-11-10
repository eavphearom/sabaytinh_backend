
import logging

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.brand import Brand
from app.repositories.brand_repository import BrandRepository
from app.schemas.brand_schema import BrandResponseSchema
from app.exceptions.api_exception import (
    BadRequestException,
    DuplicateException,
    ResourceNotFoundException,
)
from app.utils.file_util import FileUtil
from app.enums.image_directory import ImageDirectory
from app.utils.slug_util import SlugUtil
from app.utils.date_util import DateUtil


logger = logging.getLogger(__name__)


class BrandService:

    def __init__(self):
        self.repository = BrandRepository()
        self.schema = BrandResponseSchema()

    # Get paginated brands
    def get_paginated(self, filters):
        result = self.repository.find_paginated(filters)

        return {
            **result,
            "items": self.schema.dump(result["items"], many=True)
        }

    # Get brand by ID
    def get_by_id(self, brand_id):
        brand = self.repository.find_by_id(brand_id)

        if brand is None:
            raise ResourceNotFoundException("Brand not found")

        return self.schema.dump(brand)

    # Create brand
    def create(self, data, user_id, logo_file=None):
        data = data.copy()
        name = data["name"].strip()

        if not name:
            raise BadRequestException("Name is required")

        slug = SlugUtil.generate(name)

        if len(slug) > 150:
            raise BadRequestException("Brand slug is too long")

        if self.repository.find_by_slug(slug):
            raise DuplicateException("Brand slug already exists")

        new_logo = None

        try:
            # Save optional logo
            if logo_file:
                new_logo = FileUtil.save_image(
                    logo_file, ImageDirectory.BRAND
                )
                data["logo"] = new_logo

            brand = Brand(
                **{
                    **data,
                    "name": name,
                    "slug": slug,
                    "is_active": data.get("is_active", True),
                },
                created_at=DateUtil.now(),
                create_uid=user_id,
            )

            db.session.add(brand)
            db.session.flush()

            result = self.schema.dump(brand)
            db.session.commit()
            return result

        except Exception as error:
            db.session.rollback()

            if new_logo:
                try:
                    FileUtil.delete_image(new_logo)
                except OSError:
                    logger.exception("Failed to clean up new logo")

            if isinstance(error, IntegrityError):
                raise DuplicateException(
                    "Brand slug already exists"
                ) from error

            raise

    # Update brand
    def update(self, brand_id, data, user_id, logo_file=None):
        brand = self.repository.find_by_id(brand_id)

        if brand is None:
            raise ResourceNotFoundException("Brand not found")

        data = data.copy()

        if "name" in data:
            name = data["name"].strip()

            if not name:
                raise BadRequestException("Name is required")

            slug = SlugUtil.generate(name)

            if len(slug) > 150:
                raise BadRequestException("Brand slug is too long")

            existing = self.repository.find_by_slug(slug)

            if existing and existing.id != brand_id:
                raise DuplicateException("Brand slug already exists")

            data["name"] = name
            data["slug"] = slug

        old_logo = brand.logo
        new_logo = None

        try:
            # Replace logo if a new file is uploaded
            if logo_file:
                new_logo = FileUtil.save_image(
                    logo_file, ImageDirectory.BRAND
                )
                data["logo"] = new_logo

            # Update provided fields only
            for field, value in data.items():
                setattr(brand, field, value)

            brand.updated_at = DateUtil.now()
            brand.update_uid = user_id

            db.session.flush()
            result = self.schema.dump(brand)
            db.session.commit()

        except Exception as error:
            db.session.rollback()

            if new_logo:
                try:
                    FileUtil.delete_image(new_logo)
                except OSError:
                    logger.exception("Failed to clean up new logo")

            if isinstance(error, IntegrityError):
                raise DuplicateException(
                    "Brand slug already exists"
                ) from error

            raise

        # Remove old logo after successful commit
        if new_logo and old_logo != new_logo:
            try:
                FileUtil.delete_image(old_logo)
            except OSError:
                logger.exception("Failed to delete old brand logo")

        return result

    # Soft delete brand
    def delete(self, brand_id, user_id):
        try:
            deleted = self.repository.soft_delete_by_id(
                brand_id,
                deleted_uid=user_id,
            )

            if not deleted:
                raise ResourceNotFoundException("Brand not found")

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
