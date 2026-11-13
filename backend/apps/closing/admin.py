from typing import Any

from django.contrib import admin
from django.http import HttpRequest

from .models import LotResult, PartnershipResult


@admin.register(LotResult)
class LotResultAdmin(admin.ModelAdmin[LotResult]):
    """For looking only: a lot is closed and reopened through the services, which check and audit it."""

    list_display = ("batch", "status", "net_result", "partner_share", "closed_at", "organization")
    list_filter = ("organization", "status")

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False


@admin.register(PartnershipResult)
class PartnershipResultAdmin(admin.ModelAdmin[PartnershipResult]):
    """For looking only: frozen by the lot closings (D-324)."""

    list_display = ("partnership", "status", "net_result", "partner_share", "closed_at", "organization")
    list_filter = ("organization", "status")

    def has_add_permission(self, request: HttpRequest, *args: Any) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: Any = None) -> bool:
        return False
