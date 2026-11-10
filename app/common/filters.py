
from dataclasses import dataclass
from flask import request

from app.exceptions.api_exception import BadRequestException


@dataclass
class BaseFilter:
    page_no: int = 1
    per_page: int = 10
    search: str = ""
    sort_by: str = "id"
    sort_dir: str = "desc"
    include_deleted: bool = False

    @classmethod
    def from_request(cls, allow_deleted=False):
        args = request.args

        try:
            page_no = int(args.get("page_no", 1))
            per_page = int(args.get("per_page", 10))
        except (ValueError, TypeError):
            raise BadRequestException(
                "page_no and per_page must be integers"
            )

        if page_no < 1:
            raise BadRequestException(
                "page_no must be greater than 0"
            )

        if not 1 <= per_page <= 100:
            raise BadRequestException(
                "per_page must be between 1 and 100"
            )

        sort_dir = args.get("sort_dir", "desc").lower()

        if sort_dir not in ("asc", "desc"):
            raise BadRequestException(
                "sort_dir must be asc or desc"
            )

        deleted_value = args.get(
            "include_deleted", "false"
        ).lower()

        if deleted_value not in ("true", "false"):
            raise BadRequestException(
                "include_deleted must be true or false"
            )

        include_deleted = deleted_value == "true"

        if include_deleted and not allow_deleted:
            raise BadRequestException(
                "include_deleted is not allowed"
            )

        return cls(
            page_no=page_no,
            per_page=per_page,
            search=args.get("search", "").strip(),
            sort_by=args.get("sort_by", "id"),
            sort_dir=sort_dir,
            include_deleted=include_deleted,
        )
