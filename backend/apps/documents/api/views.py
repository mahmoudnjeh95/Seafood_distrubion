from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import FileResponse, Http404
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import OpenApiParameter, extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of
from apps.documents import services
from apps.documents.models import SentEmail

PdfState = inline_serializer("PdfState", {"status": serializers.ChoiceField(choices=["pending", "failed"])})


class DocumentPdfView(APIView):
    permission_classes: tuple[type[BasePermission], ...] = (ReadOfficeWriteOwnerOrManager,)

    @extend_schema(
        operation_id="getDocumentPdf",
        parameters=[OpenApiParameter("retry", bool, description="Try again after a failure.")],
        responses={(200, "application/pdf"): OpenApiTypes.BINARY, 202: PdfState, 500: PdfState},
    )
    def get(self, request: Request, kind: str, object_id: int) -> Response | FileResponse:
        """The PDF of a quote (`quote`), invoice (`invoice`), credit note (`credit_note`) or customer payment
        receipt (`receipt`). 200 is the file; 202 `pending` means it is being made (ask again in a second);
        500 `failed` means the last attempt failed (`?retry=1` tries again). Office data: drivers get 403."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        organization = membership.organization
        if not services.is_known(kind):
            raise Http404
        if not services.may_read(kind, membership.role):
            raise PermissionDenied
        retry = request.query_params.get("retry") in {"1", "true"}
        try:
            row = services.request_pdf(organization=organization, kind=kind, object_id=object_id, retry=retry)
            current = services.printable(organization, kind, object_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        if row is None:
            row = services.current_file(organization=organization, kind=kind, object_id=object_id)
        if row is None:
            if services.failure_of(organization=organization, kind=kind, object_id=object_id):
                return Response({"status": "failed"}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
            return Response({"status": "pending"}, status=status.HTTP_202_ACCEPTED)
        response = FileResponse(row.file.open("rb"), content_type="application/pdf")
        response["Content-Disposition"] = f'inline; filename="{current.filename}"'
        response["Cache-Control"] = "private, no-store"
        return response


class SentEmailRowSerializer(serializers.Serializer[Any]):
    to = serializers.CharField(read_only=True)
    subject = serializers.CharField(read_only=True)
    sent_at = serializers.DateTimeField(read_only=True)
    # Why it did not leave; empty when it did.
    error = serializers.CharField(read_only=True)


class EmailDraftSerializer(serializers.Serializer[Any]):
    # Every address the party has (D-222): the window ticks them all and may drop or add some for this send.
    to = serializers.ListField(child=serializers.CharField(), read_only=True)
    subject = serializers.CharField(read_only=True)
    body = serializers.CharField(read_only=True)
    # The last sends of this document, newest first.
    sent = SentEmailRowSerializer(many=True, read_only=True)


class EmailWriteSerializer(serializers.Serializer[Any]):
    to = serializers.ListField(child=serializers.EmailField(), allow_empty=False, max_length=10)
    subject = serializers.CharField(max_length=255)
    body = serializers.CharField(allow_blank=True, max_length=5000)


class DocumentEmailView(APIView):
    permission_classes: tuple[type[BasePermission], ...] = (ReadOfficeWriteOwnerOrManager,)

    def _checked(self, request: Request, kind: str, object_id: int) -> Any:
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        if not services.is_known(kind):
            raise Http404
        if not services.may_read(kind, membership.role):
            raise PermissionDenied
        try:
            services.printable(membership.organization, kind, object_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        return membership

    @extend_schema(operation_id="getDocumentEmailDraft", responses=EmailDraftSerializer)
    def get(self, request: Request, kind: str, object_id: int) -> Response:
        """What "Envoyer par e-mail" proposes for this document (D-206): the party's addresses (D-222), a subject naming
        the document and the company, a short message; and the last times it was sent."""
        membership = self._checked(request, kind, object_id)
        draft = services.email_draft(membership.organization, kind, object_id)
        sent = list(
            SentEmail.objects.for_organization(membership.organization).filter(kind=kind, object_id=object_id)[:5]
        )
        return Response(EmailDraftSerializer({**draft, "sent": sent}).data)

    @extend_schema(operation_id="sendDocumentEmail", request=EmailWriteSerializer, responses={204: None})
    def post(self, request: Request, kind: str, object_id: int) -> Response:
        """Send the document's PDF by e-mail from the company address (D-206). Office roles that may read it."""
        membership = self._checked(request, kind, object_id)
        serializer = EmailWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.send_email(
            organization=membership.organization,
            actor=membership.user,
            kind=kind,
            object_id=object_id,
            to=data["to"],
            subject=data["subject"],
            body=data["body"],
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
