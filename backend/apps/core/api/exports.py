"""Excel export of a list, as the user sees it: the same filters and the same sort, every row, not only a page."""

from collections.abc import Sequence
from typing import Any

from django.http import HttpResponse

from apps.core.api.pagination import ordered
from apps.core.xlsx import workbook_bytes, xlsx_response

EXPORT_LIMIT = 5000
ORDERING_HELP = "Column to sort by; a leading `-` sorts descending."


class ListExport:
    """Mix in before a list view: `export_table` turns the rows into a header, lines and an optional totals line.
    The view keeps its own `get_queryset` (filters, permissions, a driver's own rows) and `ordering_columns`."""

    export_name = "export"
    export_title = "Export"

    def export_table(self, items: Sequence[Any]) -> tuple[list[str], list[list[Any]], list[Any] | None]:
        raise NotImplementedError

    def export_response(self) -> HttpResponse:
        view: Any = self  # a list view: it owns the queryset, the request and the sortable columns
        queryset = ordered(view.get_queryset(), view.request.query_params.get("ordering", ""), view.ordering_columns)
        headers, rows, totals = self.export_table(list(queryset[:EXPORT_LIMIT]))
        content = workbook_bytes(title=self.export_title, headers=headers, rows=rows, totals=totals)
        return xlsx_response(self.export_name, content)
