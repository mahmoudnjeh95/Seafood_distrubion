from drf_spectacular.utils import extend_schema
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import access
from apps.core.documents import DocumentFilters
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of
from apps.doclist import selectors

from .serializers import DocumentFilterSerializer, DocumentListSerializer


class DocumentListView(APIView):
    # Office data (D-032): owner, manager and accountant read; drivers 403. Read only: actions use each app's own
    # endpoints, which check the role again.
    permission_classes: tuple[type[BasePermission], ...] = (ReadOfficeWriteOwnerOrManager,)

    @extend_schema(
        operation_id="listDocuments", parameters=[DocumentFilterSerializer], responses=DocumentListSerializer
    )
    def get(self, request: Request) -> Response:
        """Quotes, BL, invoices, credit notes, purchase orders, receipts and supplier invoices of the organization,
        newest day first (at most 1000; `truncated` says when there were more). Each row names the documents it
        came from (`parents`) and the actions the person may take next (`actions`), so the page can draw the
        chain DV → BL → FA → AV and BA → BR → FF and offer only what would succeed."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        query = DocumentFilterSerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        data = query.validated_data
        filters = DocumentFilters(
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            search=data["search"],
            types=data["types"],
        )
        found = selectors.document_list(
            membership.organization,
            filters,
            may_write=access.can(membership, "documents", access.Level.WRITE),
            tone=data.get("tone", ""),
        )
        payload = {
            "results": [{**vars(row), "key": row.key} for row in found.rows],
            "total": found.total,
            "truncated": found.truncated,
        }
        return Response(DocumentListSerializer(payload).data)
