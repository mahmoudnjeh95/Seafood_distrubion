from django.urls import path

from . import views

urlpatterns = [
    path("whatsapp/webhook", views.WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
]
