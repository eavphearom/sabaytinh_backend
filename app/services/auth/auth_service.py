
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models.role import Role
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider
from app.repositories.user_repository import UserRepository
from app.security.password_utils import hash_password
from app.exceptions.api_exception import (
    BadRequestException,
    DuplicateException,
    ResourceNotFoundException,
)

import hmac
import uuid

from datetime import datetime, timezone, timedelta
from flask import current_app

from app.models.refresh_session import RefreshSession
from app.security.password_utils import verify_password
from app.security.jwt_utils import (
    generate_access_token,
    generate_refresh_token,
    hash_refresh_token,
    parse_session_id,
)
from app.exceptions.api_exception import UnauthorizedException


class AuthService:

    def __init__(self):
        self.user_repository = UserRepository()

    def register(self, data: dict):
        username = data["username"].strip()
        email = data["email"].strip().lower()

        if not username:
            raise BadRequestException("Username is required")

        if self.user_repository.find_by_email(email):
            raise DuplicateException("Email already exists")

        role = db.session.scalar(
            select(Role).where(
                Role.code == "USER",
                Role.is_active.is_(True),
                Role.is_deleted.is_(False),
            )
        )

        if role is None:
            raise ResourceNotFoundException(
                "Default USER role not found"
            )

        try:
            user = User(
                username=username,
                email=email,
                password=hash_password(data["password"]),
                phone=data.get("phone"),
                role_id=role.id,
                status="ACTIVE",
            )

            db.session.add(user)
            db.session.flush()

            # Initial convention: use the local user ID
            # as the LOCAL provider identifier.
            provider = UserAuthProvider(
                user_id=user.id,
                provider="LOCAL",
                provider_user_id=str(user.id),
            )

            db.session.add(provider)
            db.session.commit()

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "phone": user.phone,
                "role": role.code,
                "status": user.status,
            }

        except IntegrityError:
            db.session.rollback()
            raise DuplicateException(
                "Account could not be created due to a duplicate value"
            )

        except Exception:
            db.session.rollback()
            raise
    
    # login
    
    def login(self, data: dict):
        email = data["email"].strip().lower()
        password = data["password"]

        user = self.user_repository.find_by_email(email)

        if user is None or not verify_password(
            password, user.password
        ):
            raise UnauthorizedException(
                "Invalid email or password"
            )

        if user.status != "ACTIVE":
            raise UnauthorizedException(
                "Your account is not active"
            )

        if (
            user.role is None
            or not user.role.is_active
            or user.role.is_deleted
        ):
            raise UnauthorizedException(
                "Account role is unavailable"
            )

        try:
            session_id = uuid.uuid4()
            now = datetime.now(timezone.utc)

            refresh_token = generate_refresh_token(
                session_id
            )

            refresh_session = RefreshSession(
                id=session_id,
                user_id=user.id,
                token_hash=hash_refresh_token(
                    refresh_token
                ),
                expires_at=now + current_app.config[
                    "JWT_REFRESH_TOKEN_EXPIRES"
                ],
                revoked=False,
            )

            db.session.add(refresh_session)
            db.session.commit()

            return {
                "id": user.id,
                "username": user.username,
                "email": user.email,
                "role": user.role.code,
                "access_token": generate_access_token(user, session_id),
                "refresh_token": refresh_token,
            }

        except Exception:
            db.session.rollback()
            raise

    def refresh(self, token: str):
        session_id = parse_session_id(token)

        if session_id is None:
            raise UnauthorizedException(
                "Invalid refresh token"
            )

        try:
            # Lock row to prevent simultaneous refreshes.
            session = db.session.scalar(
                select(RefreshSession)
                .where(RefreshSession.id == session_id)
                .with_for_update()
            )

            now = datetime.now(timezone.utc)

            if (
                session is None
                or session.revoked
                or session.expires_at <= now
                or not hmac.compare_digest(
                    session.token_hash,
                    hash_refresh_token(token)
                )
            ):
                raise UnauthorizedException(
                    "Invalid or expired refresh token"
                )

            user = db.session.get(User, session.user_id)

            if (
                user is None
                or user.is_deleted
                or user.status != "ACTIVE"
                or user.role is None
                or user.role.is_deleted
                or not user.role.is_active
            ):
                raise UnauthorizedException(
                    "User account is unavailable"
                )

            # Rotate refresh-token secret.
            new_refresh_token = generate_refresh_token(
                session.id
            )

            session.token_hash = hash_refresh_token(
                new_refresh_token
            )

            db.session.commit()

            return {
                "access_token": generate_access_token(user,session.id),
                "refresh_token": new_refresh_token,
                "token_type": "Bearer",
            }

        except Exception:
            db.session.rollback()
            raise

    
    def logout(self, session_id: str, user_id: str):
        try:
            session_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError, AttributeError):
            raise UnauthorizedException(
                "Invalid session"
            )

        try:
            # Lock the session row.
            session = db.session.scalar(
                select(RefreshSession)
                .where(
                    RefreshSession.id == session_uuid,
                    RefreshSession.user_id == int(user_id)
                )
                .with_for_update()
            )

            if session is None or session.revoked:
                raise UnauthorizedException(
                    "Session not found or already revoked"
                )

            session.revoked = True

            db.session.commit()

        except Exception:
            db.session.rollback()
            raise
