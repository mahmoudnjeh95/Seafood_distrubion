from django.urls import path

from . import chat_views, views

urlpatterns = [
    path("whatsapp/webhook", views.WhatsAppWebhookView.as_view(), name="whatsapp-webhook"),
    path("assistant/chat", chat_views.ChatDetailView.as_view(), name="assistant-chat"),
    path("assistant/chat/messages", chat_views.ChatQuestionView.as_view(), name="assistant-chat-messages"),
    path(
        "assistant/chat/messages/<int:message_id>/speech",
        chat_views.ChatSpeechView.as_view(),
        name="assistant-chat-speech",
    ),
]
