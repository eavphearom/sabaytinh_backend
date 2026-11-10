
import hashlib
import secrets
import uuid
from datetime import datetime, timezone

from flask_jwt_extended import create_access_token
from sqlalchemy import select

from app.extensions import db
from app.models.refresh_session import RefreshSession
from app.common.api_response import error_response


def generate_access_token(user, session_id):
    return create_access_token(
        identity=str(user.id),
        additional_claims={
            "sid": str(session_id)
        }
    )


def generate_refresh_token(session_id):
    secret = secrets.token_urlsafe(48)
    return f"{session_id}.{secret}"


def hash_refresh_token(token):
    return hashlib.sha256(
        token.encode("utf-8")
    ).hexdigest()


def parse_session_id(token):
    try:
        session_id, secret = token.split(".", 1)

        if not secret or len(secret) > 256:
            return None

        return uuid.UUID(session_id)

    except (ValueError, AttributeError):
        return None


def register_jwt_handlers(jwt):

    def unauthorized(message):
        return error_response(
            message=message,
            status="Unauthorized",
            data=[],
            http_status=401
        )

    @jwt.unauthorized_loader
    def missing_token(message):
        return unauthorized(message)

    @jwt.invalid_token_loader
    def invalid_token(message):
        return unauthorized(message)

    @jwt.expired_token_loader
    def expired_token(header, payload):
        return unauthorized("Token has expired")

    @jwt.revoked_token_loader
    def revoked_token(header, payload):
        return unauthorized("Token has been revoked")

    @jwt.token_in_blocklist_loader
    def check_token_revoked(header, payload):
        session_id = payload.get("sid")

        if not session_id:
            return True

        try:
            session_uuid = uuid.UUID(session_id)
        except (ValueError, TypeError, AttributeError):
            return True

        session = db.session.scalar(
            select(RefreshSession).where(
                RefreshSession.id == session_uuid
            )
        )

        if session is None:
            return True

        if session.revoked:
            return True

        if session.expires_at <= datetime.now(timezone.utc):
            return True

        # Token must belong to the session owner.
        if payload.get("sub") != str(session.user_id):
            return True

        return False
