
class ApiException(Exception):
    def __init__(
        self,
        message="Error",
        status_code=400,
        status="Bad Request"
    ):
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.status = status


class BadRequestException(ApiException):
    def __init__(self, message="Bad Request"):
        super().__init__(message, 400, "Bad Request")


class UnauthorizedException(ApiException):
    def __init__(self, message="Unauthorized"):
        super().__init__(message, 401, "Unauthorized")


class ForbiddenException(ApiException):
    def __init__(self, message="Forbidden"):
        super().__init__(message, 403, "Forbidden")


class ResourceNotFoundException(ApiException):
    def __init__(self, message="Resource not found"):
        super().__init__(message, 404, "Not Found")


class DuplicateException(ApiException):
    def __init__(self, message="Duplicate Data"):
        super().__init__(message, 409, "Conflict")


class ValidationException(ApiException):
    def __init__(self, message="Unprocessable"):
        super().__init__(message, 422, "Unprocessable Entity")


class UnexpectedException(ApiException):
    def __init__(self, message="Internal Server Error"):
        super().__init__(
            message, 500, "Internal Server Error"
        )


class PaymentGatewayUnavailableException(ApiException):
    def __init__(self, message="Payment gateway unavailable"):
        super().__init__(
            message, 503, "Service Unavailable"
        )
