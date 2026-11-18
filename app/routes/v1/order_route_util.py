from flask import request

from app.common.api_response import ApiResponse
from app.exceptions.api_exception import BadRequestException


def json_payload(*, example=None, allow_empty=False):
    hint = f" Send a JSON object, for example: {example}" if example else ""
    if allow_empty and not request.get_data(cache=True).strip():
        return {}
    if not request.is_json:
        raise BadRequestException("Content type must be application/json." + hint)
    if not request.get_data(cache=True).strip():
        raise BadRequestException("JSON request body is required." + hint)
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise BadRequestException("Invalid JSON request body; expected a JSON object." + hint)
    return data


def paginated(result):
    return ApiResponse.paginate(
        data=result["items"], per_page=result["per_page"], total=result["total"],
        total_page=result["total_page"], page_no=result["page_no"],
    )
