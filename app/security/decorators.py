
from functools import wraps
from flask import g

from flask_jwt_extended import jwt_required, get_jwt_identity

from app.repositories.user_repository import UserRepository
from app.exceptions.api_exception import (
    UnauthorizedException,
    ForbiddenException,
)


def admin_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        user = UserRepository().find_by_id(
            int(get_jwt_identity())
        )

        if user is None or user.status != "ACTIVE":
            raise UnauthorizedException("User account is unavailable")

        if (
            user.role is None
            or user.role.is_deleted
            or not user.role.is_active
            or user.role.code != "ADMIN"
        ):
            raise ForbiddenException("Admin access required")

        return fn(*args, **kwargs)

    return wrapper


def customer_required(fn):
    @wraps(fn)
    @jwt_required()
    def wrapper(*args, **kwargs):
        try:
            identity = get_jwt_identity()
            if not isinstance(identity, str) or not identity.isdigit():
                raise ValueError
            user_id = int(identity)
            if not 1 <= user_id <= 9_223_372_036_854_775_807:
                raise ValueError
        except (ValueError, TypeError):
            raise UnauthorizedException("Invalid customer identity")
        user = UserRepository().find_by_id(user_id)
        if (user is None or user.status != "ACTIVE" or user.role is None
                or user.role.is_deleted or not user.role.is_active):
            raise UnauthorizedException("Customer account is unavailable")
        g.customer_id = user_id
        return fn(*args, **kwargs)
    return wrapper
