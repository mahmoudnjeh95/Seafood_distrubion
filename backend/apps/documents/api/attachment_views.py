"""Files attached to a document (D-288): list, add, open, remove."""

from typing import Any

from django.http import FileResponse, Http404
from django.urls import reverse
from drf_spectacular.utils import OpenApiResponse, extend_schema, extend_schema_field
from rest_framework import serializers, status
from rest_framework.parsers import MultiPartParser
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of
from apps.documents import services
from apps.documents.models import Attachment, AttachmentKind


class AttachmentSerializer(serializers.ModelSerializer[Attachment]):
    kind = serializers.ChoiceField(choices=AttachmentKind.choices, read_only=True)
    uploaded_by = serializers.SerializerMethodField()
    # Opened by a link (the session's cookie), not by the generated client.
    file_url = serializers.SerializerMethodField()

    class Meta:
        model = Attachment
        fields = (
            "id",
            "kind",
            "object_id",
            "name",
            "content_type",
            "size",
            "note",
            "uploaded_by",
            "uploaded_at",
            "file_url",
        )
        read_only_fields = fields

    def get_uploaded_by(self, attachment: Attachment) -> str:
        user = attachment.uploaded_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or str(user.username)

    @extend_schema_field(serializers.CharField())
    def get_file_url(self, attachment: Attachment) -> str:
        return reverse("attachment-file", args=[attachment.pk])


class AttachmentFilterSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=AttachmentKind.choices)
    object_id = serializers.IntegerField(min_value=1)


class AttachmentWriteSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=AttachmentKind.choices)
    object_id = serializers.IntegerField(min_value=1)
    # A PDF, or a photo (JPEG, PNG, WebP).
    file = serializers.FileField()
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class AttachmentBaseView(APIView):
    # Office data (D-032): owner, manager and accountant read; owner and manager add and remove; drivers 403.
    permission_classes: tuple[type[BasePermission], ...] = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    def attachment(self, attachment_id: int) -> Attachment:
        row = (
            Attachment.objects.for_organization(self.membership.organization)
            .filter(pk=attachment_id, removed_at__isnull=True)
            .select_related("uploaded_by")
            .first()
        )
        if row is None:
            raise Http404
        return row


class AttachmentListView(AttachmentBaseView):
    parser_classes = (MultiPartParser,)

    @extend_schema(
        operation_id="listAttachments",
        parameters=[AttachmentFilterSerializer],
        responses=AttachmentSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """The files attached to one document (`kind`, `object_id`), oldest first."""
        filters = AttachmentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        organization = self.membership.organization
        kind, object_id = filters.validated_data["kind"], filters.validated_data["object_id"]
        if not services.is_attachable(organization, kind, object_id):
            raise Http404
        rows = services.attachments_of(organization, kind, object_id)
        return Response(AttachmentSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="addAttachment",
        request={"multipart/form-data": AttachmentWriteSerializer},
        responses={201: AttachmentSerializer, 400: OpenApiResponse(description="Not a PDF or a photo")},
    )
    def post(self, request: Request) -> Response:
        """Attach a file to a document (D-288): a PDF of 8 MB at most, or a photo turned upright and shrunk. Owner or
        manager."""
        serializer = AttachmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        attachment = services.add_attachment(
            organization=self.membership.organization,
            actor=self.membership.user,
            kind=data["kind"],
            object_id=data["object_id"],
            upload=data["file"],
            note=data["note"],
        )
        return Response(AttachmentSerializer(attachment).data, status=status.HTTP_201_CREATED)


class AttachmentDetailView(AttachmentBaseView):
    @extend_schema(operation_id="removeAttachment", responses={204: None})
    def delete(self, request: Request, attachment_id: int) -> Response:
        """Take a file off its document: hidden from now on; the file is kept with who removed it. Owner or
        manager."""
        services.remove_attachment(attachment=self.attachment(attachment_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class AttachmentFileView(AttachmentBaseView):
    # Opened by a link, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, attachment_id: int) -> FileResponse:
        attachment = self.attachment(attachment_id)
        response = FileResponse(attachment.file.open("rb"), content_type=attachment.content_type)
        safe = attachment.name.replace('"', "")
        response["Content-Disposition"] = f'inline; filename="{safe}"'
        response["Cache-Control"] = "private, max-age=3600"
        return response
