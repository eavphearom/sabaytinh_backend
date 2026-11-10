
import logging

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.category import Category
from app.repositories.category_repository import CategoryRepository
from app.schemas.category_schema import CategoryResponseSchema
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


class CategoryService:

    def __init__(self):
        self.repository = CategoryRepository()
        self.schema = CategoryResponseSchema()

    # Get paginated categories
    def get_paginated(self, filters):
        result = self.repository.find_paginated(filters)

        return {
            **result,
            "items": self.schema.dump(result["items"], many=True)
        }

    # Get category by ID
    def get_by_id(self, category_id):
        category = self.repository.find_by_id(category_id)

        if category is None:
            raise ResourceNotFoundException("Category not found")

        return self.schema.dump(category)

    # Create category
    def create(self, data, user_id, image_file=None):
        data = data.copy()

        name = data["name"].strip()

        if not name:
            raise BadRequestException("Name is required")

        # Generate slug automatically from category name
        slug = SlugUtil.generate(name)

        if self.repository.find_by_slug(slug):
            raise DuplicateException("Category slug already exists")

        new_image = None

        try:
            # Save uploaded image if provided
            if image_file:
                new_image = FileUtil.save_image(
                    image_file,
                    ImageDirectory.CATEGORY
                )
                data["image"] = new_image

            category = Category(
                **{
                    **data,
                    "name": name,
                    "slug": slug,
                    "is_active": data.get("is_active", True),
                },
                created_at=DateUtil.now(),
                create_uid=user_id
            )

            db.session.add(category)
            db.session.flush()

            result = self.schema.dump(category)
            db.session.commit()

            return result

        except IntegrityError:
            db.session.rollback()

            if new_image:
                FileUtil.delete_image(new_image)

            raise DuplicateException("Category slug already exists")

        except Exception:
            db.session.rollback()

            if new_image:
                FileUtil.delete_image(new_image)

            raise

    # Update category
    def update(self, category_id, data, user_id, image_file=None):
        category = self.repository.find_by_id(category_id)

        if category is None:
            raise ResourceNotFoundException("Category not found")

        data = data.copy()

        # Update name and regenerate slug if name is provided
        if "name" in data:
            name = data["name"].strip()

            if not name:
                raise BadRequestException("Name is required")

            slug = SlugUtil.generate(name)

            existing = self.repository.find_by_slug(slug)

            if existing and existing.id != category_id:
                raise DuplicateException("Category slug already exists")

            data["name"] = name
            data["slug"] = slug

        old_image = category.image
        new_image = None

        try:
            # Replace image only when a new file is uploaded
            if image_file:
                new_image = FileUtil.save_image(
                    image_file,
                    ImageDirectory.CATEGORY
                )
                data["image"] = new_image

            # Update provided fields only
            for field, value in data.items():
                setattr(category, field, value)

            category.updated_at = DateUtil.now()
            category.update_uid = user_id

            db.session.flush()

            result = self.schema.dump(category)
            db.session.commit()

        except IntegrityError:
            db.session.rollback()

            if new_image:
                FileUtil.delete_image(new_image)

            raise DuplicateException("Category slug already exists")

        except Exception:
            db.session.rollback()

            if new_image:
                FileUtil.delete_image(new_image)

            raise

        # Delete old image only after successful database commit
        if new_image and old_image != new_image:
            try:
                FileUtil.delete_image(old_image)
            except OSError:
                logger.exception(
                    "Failed to delete old category image"
                )

        return result

    # Soft delete category
    def delete(self, category_id, user_id):
        try:
            deleted = self.repository.soft_delete_by_id(
                category_id,
                deleted_uid=user_id
            )

            if not deleted:
                raise ResourceNotFoundException(
                    "Category not found"
                )

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
