from django.contrib import admin
from django.http import HttpRequest

from .models import AssistantMessage, WhatsAppLink


@admin.register(WhatsAppLink)
class WhatsAppLinkAdmin(admin.ModelAdmin[WhatsAppLink]):
    list_display = ("phone", "membership", "is_active", "created_at")
    list_filter = ("organization", "is_active")
    search_fields = ("phone", "membership__user__username")


@admin.register(AssistantMessage)
class AssistantMessageAdmin(admin.ModelAdmin[AssistantMessage]):
    """Read-only: the log of what the assistant received and answered."""

    list_display = ("created_at", "link", "direction", "kind", "input_tokens", "output_tokens")
    list_filter = ("direction", "kind")

    def has_add_permission(self, request: HttpRequest) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: AssistantMessage | None = None) -> bool:
        return False
