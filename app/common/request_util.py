
from flask import request

from app.exceptions.api_exception import BadRequestException


class RequestUtil:

    @staticmethod
    def get_payload(file_field="image"):
        """Read JSON or multipart form data."""

        if request.is_json:
            data = request.get_json(silent=True)

            if not isinstance(data, dict):
                raise BadRequestException("Invalid JSON request body")

            return data, None

        if request.mimetype == "multipart/form-data":
            data = request.form.to_dict()

            # File field can be image, logo, etc.
            uploaded_file = request.files.get(file_field)

            if uploaded_file and file_field in data:
                raise BadRequestException(
                    f"Provide {file_field} as text or file, not both"
                )

            return data, uploaded_file

        raise BadRequestException(
            "Content type must be JSON or multipart/form-data"
        )
