from django.urls import path

from .views import DocumentEmailView, DocumentPdfView

urlpatterns = [
    path("documents/<str:kind>/<int:object_id>/pdf", DocumentPdfView.as_view(), name="document-pdf"),
    path("documents/<str:kind>/<int:object_id>/email", DocumentEmailView.as_view(), name="document-email"),
]
