import logging
import re

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.delivery_method import DeliveryMethod
from app.repositories.delivery_method_repository import (
    DeliveryMethodRepository,
)
from app.schemas.delivery_method_schema import (
    DeliveryMethodResponseSchema,
)
from app.enums.currency import Currency
from app.exceptions.api_exception import (
    BadRequestException,
    DuplicateException,
    ResourceNotFoundException,
)
from app.utils.date_util import DateUtil
from app.utils.file_util import FileUtil
from app.enums.image_directory import ImageDirectory


logger = logging.getLogger(__name__)


class DeliveryMethodService:

    def __init__(self):
        self.repository = DeliveryMethodRepository()
        self.response_schema = DeliveryMethodResponseSchema()

    @staticmethod
    def _code(name):
        code = re.sub(
            r"\s+",
            "_",
            name.strip().upper()
        )

        if not code or len(code) > 50:
            raise BadRequestException(
                "Generated delivery code must be 1-50 characters"
            )

        return code

    def _get(self, delivery_id, lock=False):
        query = select(DeliveryMethod).where(
            DeliveryMethod.id == delivery_id,
            DeliveryMethod.is_deleted.is_(False)
        )

        if lock:
            query = query.with_for_update()

        entity = db.session.scalar(query)

        if entity is None:
            raise ResourceNotFoundException(
                "Delivery method not found"
            )

        return entity

    def get_by_id(self, delivery_id):
        return self.response_schema.dump(
            self._get(delivery_id)
        )

    def get_paginated(
        self,
        page=1,
        page_size=10,
        search=None,
        active_only=False
    ):
        rows, total = self.repository.paginate(
            page,
            page_size,
            search,
            active_only
        )

        return {
            "items": self.response_schema.dump(
                rows,
                many=True
            ),
            "total_items": total,
            "total_pages": (
                total + page_size - 1
            ) // page_size,
            "page_no": page,
            "page_size": page_size,
        }

    @staticmethod
    def _remove_file(path):
        if path:
            try:
                FileUtil.delete_image(path)
            except OSError:
                logger.exception(
                    "Could not remove delivery logo %s",
                    path
                )

    def create(self, data, logo_file, user_id):
        code = self._code(data["name"])

        if self.repository.code_exists(code):
            raise DuplicateException(
                "Delivery method code already exists"
            )

        uploaded = None

        try:
            if logo_file is not None:
                if not logo_file.filename:
                    raise BadRequestException(
                        "Uploaded logo file is empty"
                    )

                uploaded = FileUtil.save_image(
                    logo_file,
                    ImageDirectory.DELIVERY
                )

            entity = DeliveryMethod(
                name=data["name"].strip(),
                code=code,
                fee=data["fee"],
                currency=data.get("currency", Currency.USD.value),
                estimated_min_days=data.get(
                    "estimated_min_days"
                ),
                estimated_max_days=data.get(
                    "estimated_max_days"
                ),
                logo=uploaded,
                is_active=data.get("is_active", True),
                created_at=DateUtil.now(),
                create_uid=user_id,
            )

            db.session.add(entity)
            db.session.flush()

            result = self.response_schema.dump(entity)

            db.session.commit()

            return result

        except Exception as exc:
            db.session.rollback()

            self._remove_file(uploaded)

            if isinstance(exc, IntegrityError):
                raise DuplicateException(
                    "Delivery method code already exists"
                ) from exc

            raise

    def update(
        self,
        delivery_id,
        data,
        logo_file,
        user_id
    ):
        uploaded = None
        old_logo = None

        try:
            entity = self._get(
                delivery_id,
                lock=True
            )

            code = self._code(data["name"])

            if self.repository.code_exists(
                code,
                exclude_id=entity.id
            ):
                raise DuplicateException(
                    "Delivery method code already exists"
                )

            if logo_file is not None:
                if not logo_file.filename:
                    raise BadRequestException(
                        "Uploaded logo file is empty"
                    )

                uploaded = FileUtil.save_image(
                    logo_file,
                    ImageDirectory.DELIVERY
                )

                old_logo = entity.logo
                entity.logo = uploaded

            entity.name = data["name"].strip()
            entity.code = code
            entity.fee = data["fee"]
            entity.currency = data.get(
                "currency",
                "USD"
            )

            entity.estimated_min_days = data.get(
                "estimated_min_days"
            )

            entity.estimated_max_days = data.get(
                "estimated_max_days"
            )

            entity.is_active = data.get(
                "is_active",
                True
            )

            entity.updated_at = DateUtil.now()
            entity.update_uid = user_id

            db.session.flush()

            result = self.response_schema.dump(entity)

            db.session.commit()

        except Exception as exc:
            db.session.rollback()

            self._remove_file(uploaded)

            if isinstance(exc, IntegrityError):
                raise DuplicateException(
                    "Delivery method code already exists"
                ) from exc

            raise

        # Delete old logo only after commit
        if old_logo and old_logo != uploaded:
            self._remove_file(old_logo)

        return result

    def delete(
        self,
        delivery_id,
        user_id,
        reason=None
    ):
        if reason is not None and len(reason) > 255:
            raise BadRequestException(
                "Delete reason cannot exceed 255 characters"
            )

        try:
            entity = self._get(
                delivery_id,
                lock=True
            )

            entity.is_deleted = True
            entity.deleted_at = DateUtil.now()
            entity.deleted_uid = user_id
            entity.deleted_reason = reason

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise