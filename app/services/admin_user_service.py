from app.common.filters import pagination_params
from app.exceptions.api_exception import BadRequestException
from app.repositories.user_repository import UserRepository
from app.schemas.admin_user_schema import AdminUserResponseSchema


class AdminUserService:
    def get_paginated(self, params):
        allowed = {"pageNo", "perPage", "page", "size", "page_no", "per_page", "search", "role_id"}
        if any(key not in allowed or len(params.getlist(key)) != 1 for key in params):
            raise BadRequestException("Unsupported or repeated user filter")
        page, size = pagination_params(params, page_aliases=("page",), size_aliases=("size",))
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
