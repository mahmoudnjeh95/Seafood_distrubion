import datetime as dt

from django.db.models import QuerySet
from django.utils import timezone

from apps.core.models import Membership

from .models import AssistantMessage, Channel, Direction, WhatsAppLink

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


def conversation_of(message: AssistantMessage) -> QuerySet[AssistantMessage]:
    """Every message of the conversation `message` belongs to: one per phone on WhatsApp, one per person on the
    screen."""
    if message.channel == Channel.WEB:
        return web_conversation(message.membership)
    return AssistantMessage.objects.filter(link_id=message.link_id)


def web_conversation(membership: Membership) -> QuerySet[AssistantMessage]:
    """What one person and the assistant said on the "Assistant IA" screen (D-310)."""
    return AssistantMessage.objects.filter(membership=membership, channel=Channel.WEB)


def recent_messages(
    conversation: QuerySet[AssistantMessage], *, before_id: int | None = None
) -> list[AssistantMessage]:
    """The conversation memory: the last 20 messages of the last 24 hours, oldest first."""
    rows = conversation.filter(created_at__gte=timezone.now() - HISTORY_WINDOW)
    if before_id is not None:
        rows = rows.filter(id__lt=before_id)
    return list(reversed(rows.order_by("-created_at", "-id")[:HISTORY_SIZE]))


def incoming_count_since(conversation: QuerySet[AssistantMessage], since: dt.datetime) -> int:
    return conversation.filter(direction=Direction.IN, created_at__gte=since).count()
