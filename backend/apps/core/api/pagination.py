"""Pagination for lists that keep growing (batches, movements, invoices). Short lists are not paginated."""

from collections.abc import Mapping, Sequence
from typing import Any

from django.db.models import QuerySet
from rest_framework.pagination import LimitOffsetPagination
from rest_framework.request import Request


def ordered(queryset: Any, ordering: str, columns: Mapping[str, Sequence[str]]) -> Any:
    """`queryset` sorted by `?ordering=key` / `-key` when `key` is one of the view's `columns`; else unchanged."""
    key = ordering.removeprefix("-")
    if not isinstance(queryset, QuerySet) or key not in columns:
        return queryset
    sign = "-" if ordering.startswith("-") else ""
    return queryset.order_by(*(f"{sign}{lookup}" for lookup in columns[key]), "-pk")


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
        queryset = ordered(queryset, request.query_params.get("ordering", ""), columns)
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
