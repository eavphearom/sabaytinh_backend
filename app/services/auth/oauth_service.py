import secrets
from sqlalchemy import select, update, or_
from sqlalchemy.exc import IntegrityError
from app.extensions import db
from app.models import User, Role, UserAuthProvider
from app.repositories.auth_identity_repository import AuthIdentityRepository
from app.services.auth.auth_service import AuthService
from app.services.auth.strategies.google_auth_strategy import GoogleAuthStrategy
from app.security.password_utils import hash_password
from app.exceptions.api_exception import BadRequestException, DuplicateException, UnauthorizedException


class OAuthService:
    strategies = {"google": GoogleAuthStrategy}

    def strategy(self, provider):
        if provider not in self.strategies:
            raise BadRequestException("Unsupported login provider")
        return self.strategies[provider]()

    def start(self, provider, data):
        return self.strategy(provider).start(data["code_challenge"])

    def login(self, provider, data):
        identity = self.strategy(provider).verify(data)
        repo = AuthIdentityRepository()
        try:
            repo.lock_email(identity["email"])
            link = repo.provider_account(identity["provider"], identity["subject"])
            if link:
                if link.is_deleted:
                    raise UnauthorizedException("User account is unavailable")
                user = link.user
            else:
                if repo.email_exists(identity["email"]):
                    raise DuplicateException("An account already uses this email. Sign in with your existing login method; automatic linking is not allowed.")
                role = db.session.scalar(select(Role).where(Role.code == "USER", Role.is_active.is_(True), Role.is_deleted.is_(False)))
                if role is None:
                    raise BadRequestException("Default USER role is unavailable")
                user = User(username=identity["name"], email=identity["email"],
                    password=hash_password(secrets.token_urlsafe(48)), role=role, status="ACTIVE")
                db.session.add(user)
                db.session.flush()
                db.session.add(UserAuthProvider(user_id=user.id, provider=identity["provider"], provider_user_id=identity["subject"]))
            if (user is None or user.is_deleted or user.status != "ACTIVE" or user.role is None
                    or user.role.is_deleted or not user.role.is_active):
                raise UnauthorizedException("User account is unavailable")
            if identity.get("profile"):
                # Fill existing Google accounts too, without overwriting a custom
                # upload, including one saved concurrently with this login.
                db.session.execute(update(User).where(
                    User.id == user.id,
                    or_(User.profile.is_(None), User.profile == ""),
                ).values(profile=identity["profile"]))
            return AuthService().create_session(user)
        except IntegrityError:
            db.session.rollback()
            raise DuplicateException("Account changed during login; please start again") from None
        except Exception:
            db.session.rollback()
            raise
