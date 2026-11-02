"""Pagination for lists that keep growing (batches, movements, invoices). Short lists are not paginated."""

from typing import Any

from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


class PagedList(LimitOffsetPagination):
    """`?limit=&offset=`: 50 rows by default, 200 at most. The answer carries `count`, `next`, `previous`
    and `results`.

    `?ordering=key` or `?ordering=-key` sorts the whole list by a column of the table. A view lists the keys it
    accepts in `ordering_columns` (key -> ORM lookups); an unknown key is ignored, so the default order stays. Ties
    are broken by `-pk`, which keeps pages stable."""

    default_limit = 50
    max_limit = 200

    def paginate_queryset(self, queryset: Any, request: Request, view: Any = None) -> list[Any] | None:
        columns: dict[str, tuple[str, ...]] = getattr(view, "ordering_columns", {})
        raw = request.query_params.get("ordering", "")
        key = raw.removeprefix("-")
        if isinstance(queryset, QuerySet) and key in columns:
            descending = raw.startswith("-")
            queryset = queryset.order_by(*(f"-{lookup}" if descending else lookup for lookup in columns[key]), "-pk")
        return super().paginate_queryset(queryset, request, view)

    def get_schema_operation_parameters(self, view: Any) -> list[dict[str, Any]]:
        parameters = super().get_schema_operation_parameters(view)
        if getattr(view, "ordering_columns", None):
            parameters.append(
                {
                    "name": "ordering",
                    "required": False,
                    "in": "query",
                    "description": "Column to sort by; a leading `-` sorts descending.",
                    "schema": {"type": "string"},
                }
            )
        return parameters
