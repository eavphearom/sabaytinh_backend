
from dataclasses import dataclass
from flask import request

from app.exceptions.api_exception import BadRequestException


def pagination_params(args, *, default_size=10, page_aliases=(), size_aliases=()):
    """Canonical API names are pageNo/perPage; retain existing client aliases."""
    def read(canonical, aliases, default):
        names = [name for name in (canonical, *aliases) if name in args]
        if len(names) > 1 or any(len(args.getlist(name)) != 1 for name in names):
            raise BadRequestException(f"Use {canonical} only once; do not combine pagination aliases")
        try:
            return int(args[names[0]]) if names else default
        except (ValueError, TypeError):
            raise BadRequestException(f"{canonical} must be an integer") from None

    page = read("pageNo", ("page_no", *page_aliases), 1)
    size = read("perPage", ("per_page", *size_aliases), default_size)
    if page < 1:
        raise BadRequestException("pageNo must be greater than 0")
    if not 1 <= size <= 100:
        raise BadRequestException("perPage must be between 1 and 100")
    if (page - 1) * size > 9_223_372_036_854_775_807:
        raise BadRequestException("Requested page offset is too large")
    return page, size


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

        page_no, per_page = pagination_params(args)

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
