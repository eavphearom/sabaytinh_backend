
from sqlalchemy import select, func

from app.extensions import db
from app.exceptions.api_exception import BadRequestException


class PaginationUtil:

    @staticmethod
    def paginate(query, model, filters, allowed_sort_fields):
        if filters.sort_by not in allowed_sort_fields:
            raise BadRequestException(
                f"Invalid sort_by: {filters.sort_by}"
            )

        sort_column = getattr(model, filters.sort_by)

        if filters.sort_dir == "desc":
            order = sort_column.desc()
        else:
            order = sort_column.asc()

        total = db.session.scalar(
            select(func.count()).select_from(
                query.order_by(None).subquery()
            )
        ) or 0

        items = db.session.scalars(
            query.order_by(order, model.id.asc())
            .offset((filters.page_no - 1) * filters.per_page)
            .limit(filters.per_page)
        ).all()

        return {
            "items": items,
            "per_page": filters.per_page,
            "total": total,
            "total_page": (
                total + filters.per_page - 1
            ) // filters.per_page,
            "page_no": filters.page_no,
        }
