import hashlib
from sqlalchemy import select, func
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models.user import User
from app.models.user_auth_provider import UserAuthProvider


class AuthIdentityRepository:
    @staticmethod
    def lock_email(email):
        # Share with local registration; no new persistence or migration required.
        key = int.from_bytes(hashlib.sha256(("auth-email:" + email).encode()).digest()[:8], "big", signed=True)
        db.session.execute(select(func.pg_advisory_xact_lock(key)))

    @staticmethod
    def provider_account(provider, subject):
        # Include deleted links so deleting an account cannot silently recreate it.
        return db.session.scalar(select(UserAuthProvider).options(
            joinedload(UserAuthProvider.user).joinedload(User.role)).where(
                UserAuthProvider.provider == provider,
                UserAuthProvider.provider_user_id == subject,
            ).order_by(UserAuthProvider.is_deleted.asc(), UserAuthProvider.id.desc()).limit(1))

    @staticmethod
    def email_exists(email):
        return db.session.scalar(select(User.id).where(func.lower(User.email) == email).limit(1)) is not None
