from app.exceptions.api_exception import BadRequestException
from app.repositories.user_repository import UserRepository
from app.schemas.admin_user_schema import AdminUserResponseSchema


class AdminUserService:
    def get_paginated(self, params):
        allowed = {"page", "size", "page_no", "per_page", "search", "role_id"}
        if any(key not in allowed or len(params.getlist(key)) != 1 for key in params):
            raise BadRequestException("Unsupported or repeated user filter")
        if ("page" in params and "page_no" in params) or ("size" in params and "per_page" in params):
            raise BadRequestException("Use only one name for each pagination parameter")
        try:
            page = int(params.get("page", params.get("page_no", "1")))
            size = int(params.get("size", params.get("per_page", "10")))
        except (ValueError, TypeError):
            raise BadRequestException("Page and size must be integers") from None
        if page < 1 or not 1 <= size <= 100 or (page - 1) * size > 9_223_372_036_854_775_807:
            raise BadRequestException("Page must be positive and size must be between 1 and 100")
        repository = UserRepository()
        role_id = None
        if "role_id" in params:
            try:
                role_id = int(params["role_id"])
            except (ValueError, TypeError):
                raise BadRequestException("role_id must be a positive integer") from None
            if not 1 <= role_id <= 9_223_372_036_854_775_807 or not repository.role_id_exists(role_id):
                raise BadRequestException("Invalid role_id filter")
        result = repository.find_admin_paginated(page, size, params.get("search", "").strip(), role_id)
        return {**result, "items": AdminUserResponseSchema(many=True).dump(result["items"])}
