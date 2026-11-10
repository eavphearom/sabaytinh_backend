from flask import request

from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException


def json_payload():
    if not request.is_json:
        raise BadRequestException("Content type must be application/json")
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequestException("Invalid JSON request body")
    return data


def paginated(result):
    return ApiResponse.paginate(
        data=result["items"], per_page=result["per_page"], total=result["total"],
        total_page=result["total_page"], page_no=result["page_no"],
    )
