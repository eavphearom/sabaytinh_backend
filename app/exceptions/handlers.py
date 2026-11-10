
import logging

from flask import Flask
from werkzeug.exceptions import HTTPException
from sqlalchemy.exc import IntegrityError
from marshmallow import ValidationError

from app.extensions import db
from app.common.api_response import error_response
from app.exceptions.api_exception import ApiException

logger = logging.getLogger(__name__)


def first_validation_message(messages):
    """Extract the first validation message."""
    if isinstance(messages, dict):
        for value in messages.values():
            return first_validation_message(value)

    if isinstance(messages, list):
        for value in messages:
            return first_validation_message(value)

    return str(messages)


def register_error_handlers(app: Flask):

    @app.errorhandler(ApiException)
    def handle_api_exception(error):
        db.session.rollback()
        return error_response(
            message=error.message,
            status=error.status,
            data=[],
            http_status=error.status_code
        )

    @app.errorhandler(ValidationError)
    def handle_validation_error(error):
        return error_response(
            message=first_validation_message(error.messages),
            status="Bad Request",
            data=[],
            http_status=400
        )

    @app.errorhandler(IntegrityError)
    def handle_integrity_error(error):
        db.session.rollback()
        logger.warning(
            "Database integrity error",
            exc_info=True
        )

        return error_response(
            message="Database constraint violation",
            status="Conflict",
            data=[],
            http_status=409
        )

    @app.errorhandler(HTTPException)
    def handle_http_exception(error):
        return error_response(
            message=error.description,
            status=error.name,
            data=[],
            http_status=error.code or 500
        )

    @app.errorhandler(Exception)
    def handle_unexpected_error(error):
        db.session.rollback()
        logger.exception("Unexpected server error")

        return error_response(
            message="Internal Server Error",
            status="Something went wrong",
            data=[],
            http_status=500
        )
