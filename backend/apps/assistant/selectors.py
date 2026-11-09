import datetime as dt

from django.utils import timezone

from .models import AssistantMessage, Direction, WhatsAppLink

HISTORY_SIZE = 20
HISTORY_WINDOW = dt.timedelta(hours=24)


def link_for_phone(phone: str) -> WhatsAppLink | None:
    """The active link of an active user in an active organization, or None."""
    return (
        WhatsAppLink.objects.filter(
            phone=phone,
            is_active=True,
            membership__is_active=True,
            membership__user__is_active=True,
            organization__is_active=True,
        )
        .select_related("membership__user", "membership__organization", "organization")
        .first()
    )


def recent_messages(link: WhatsAppLink, *, before_id: int | None = None) -> list[AssistantMessage]:
    """The conversation memory: the last 20 messages of the last 24 hours, oldest first."""
    rows = AssistantMessage.objects.filter(link=link, created_at__gte=timezone.now() - HISTORY_WINDOW)
    if before_id is not None:
        rows = rows.filter(id__lt=before_id)
    return list(reversed(rows.order_by("-created_at", "-id")[:HISTORY_SIZE]))


def incoming_count_since(link: WhatsAppLink, since: dt.datetime) -> int:
    return AssistantMessage.objects.filter(link=link, direction=Direction.IN, created_at__gte=since).count()
