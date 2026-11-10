
from flask import jsonify


class ApiResponse:

    @staticmethod
    def response(
        data=None,
        error=False,
        status="OK",
        message="Success",
        pagination=None,
        http_status=200
    ):
        body = {
            "error": error,
            "status": status,
            "message": message,
        }

        if pagination is not None:
            body["pagination"] = pagination

        if data is not None:
            body["data"] = data

        return jsonify(body), http_status

    @staticmethod
    def success(
        data=None,
        message="Success",
        status="OK",
        http_status=200
    ):
        return ApiResponse.response(
            data=data,
            message=message,
            status=status,
            http_status=http_status
        )

    @staticmethod
    def error(
        message="Error",
        status="Error",
        data=None,
        http_status=400
    ):
        return ApiResponse.response(
            error=True,
            status=status,
            message=message,
            data=data,
            http_status=http_status
        )

    @staticmethod
    def paginate(
        data,
        per_page,
        total,
        total_page,
        page_no
    ):
        return ApiResponse.response(
            data=data,
            pagination={
                "per_page": per_page,
                "total": total,
                "total_page": total_page,
                "page_no": page_no
            }
        )


# Backward compatibility with existing code
api_response = ApiResponse.response
success_response = ApiResponse.success
error_response = ApiResponse.error
paginate_response = ApiResponse.paginate
