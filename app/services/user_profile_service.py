import logging

from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.user import User
from app.exceptions.api_exception import (
    BadRequestException,
    DuplicateException,
    UnauthorizedException,
)
from app.utils.file_util import FileUtil
from app.utils.date_util import DateUtil
from app.enums.image_directory import ImageDirectory


logger = logging.getLogger(__name__)


class UserProfileService:

    @staticmethod
    def _serialize(user):
        return {
            "id": user.id,
            "username": user.username,
            "email": user.email,
            "phone": user.phone,
            "profile": (
                FileUtil.get_image_url(user.profile)
                if user.profile else None
            ),
            "role": user.role.code,
            "status": user.status,
        }

    def update_me(self, user_id, data, profile_file=None):
        if not data and profile_file is None:
            raise BadRequestException(
                "Submit at least one profile field or image"
            )

        new_path = None
        old_path = None

        try:
            user = db.session.scalar(
                select(User)
                .where(
                    User.id == user_id,
                    User.is_deleted.is_(False)
                )
                .with_for_update()
            )

            if (
                user is None
                or user.status != "ACTIVE"
                or user.role is None
                or user.role.is_deleted
                or not user.role.is_active
            ):
                raise UnauthorizedException(
                    "User account is unavailable"
                )

            # Update username
            if "username" in data:
                username = data["username"].strip()

                if len(username) < 3:
                    raise BadRequestException(
                        "Username must contain at least 3 characters"
                    )

                existing_id = db.session.scalar(
                    select(User.id).where(
                        func.lower(User.username) == username.lower(),
                        User.id != user.id,
                        User.is_deleted.is_(False),
                    )
                )

                if existing_id is not None:
                    raise DuplicateException(
                        "Username already exists"
                    )

                user.username = username

            # Update email
            if "email" in data:
                email = data["email"].strip().lower()

                existing_id = db.session.scalar(
                    select(User.id).where(
                        func.lower(User.email) == email,
                        User.id != user.id,
                        User.is_deleted.is_(False),
                    )
                )

                if existing_id is not None:
                    raise DuplicateException(
                        "Email already exists"
                    )

                user.email = email

            # Update phone
            if "phone" in data:
                user.phone = (
                    data["phone"].strip()
                    if data["phone"] is not None
                    else None
                )

            # Update profile image
            if profile_file is not None:
                if not profile_file.filename:
                    raise BadRequestException(
                        "Profile image is required"
                    )

                new_path = FileUtil.save_image(
                    profile_file,
                    ImageDirectory.PROFILE
                )

                old_path = user.profile
                user.profile = new_path

            # Audit information
            user.updated_at = DateUtil.now()
            user.update_uid = user.id

            db.session.flush()

            result = self._serialize(user)

            db.session.commit()

        except IntegrityError as exc:
            db.session.rollback()

            if new_path:
                try:
                    FileUtil.delete_image(new_path)
                except OSError:
                    logger.exception(
                        "Failed to clean up %s", new_path
                    )

            raise DuplicateException(
                "Username or email already exists"
            ) from exc

        except Exception:
            db.session.rollback()

            if new_path:
                try:
                    FileUtil.delete_image(new_path)
                except OSError:
                    logger.exception(
                        "Failed to clean up %s", new_path
                    )

            raise

        # Delete replaced image only after successful commit
        if old_path and old_path != new_path:
            try:
                FileUtil.delete_image(old_path)
            except OSError:
                logger.exception(
                    "Failed to delete replaced profile image %s",
                    old_path
                )

        return result