from django.urls import path

from .attachment_views import AttachmentDetailView, AttachmentFileView, AttachmentListView
from .views import DocumentEmailView, DocumentPdfView

urlpatterns = [
    path("attachments", AttachmentListView.as_view(), name="attachment-list"),
    path("attachments/<int:attachment_id>", AttachmentDetailView.as_view(), name="attachment-detail"),
    path("attachments/<int:attachment_id>/file", AttachmentFileView.as_view(), name="attachment-file"),
    path("documents/<str:kind>/<int:object_id>/pdf", DocumentPdfView.as_view(), name="document-pdf"),
    path("documents/<str:kind>/<int:object_id>/email", DocumentEmailView.as_view(), name="document-email"),
]
