"""Background work of the assistant: answer a received message, or tell an unknown number it is not allowed."""

import datetime as dt
import logging

import anthropic
from celery import shared_task
from django.conf import settings
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.core.locks import lock_until_commit

from . import agent, services
from .access import may_use
from .models import AssistantMessage, MessageKind
from .selectors import incoming_count_since, recent_messages
from .whatsapp import WhatsAppError, get_client

logger = logging.getLogger(__name__)

NOT_ALLOWED = "Ce numéro n'est pas autorisé à utiliser l'assistant Frutti Del Mare."
DISABLED = "L'assistant est désactivé pour le moment."
TOO_MANY = "Trop de messages, réessayez dans un moment."
TEXT_ONLY = "Pour le moment, j'accepte seulement les messages écrits."
TECHNICAL = "Désolé, un problème technique. Réessayez dans quelques minutes."
MAX_PER_HOUR = 60
# An unknown number is told once a day at most: each refusal is a message Meta may bill.
REFUSAL_EVERY = 24 * 3600


# Up to seven calls to Claude: longer than the default limit of 120 s.
@shared_task(name="assistant.handle_message", time_limit=300)  # type: ignore[untyped-decorator]
def handle_message(message_id: int) -> None:
    """Answer one received message. Messages of one phone are answered one after the other."""
    incoming = AssistantMessage.objects.select_related("link__membership__user", "organization").get(pk=message_id)
    link = incoming.link
    membership = link.membership
    whatsapp = get_client()
    with transaction.atomic():
        lock_until_commit(f"assistant:{link.pk}")
        usage = agent.AgentReply(text="")
        try:
            if not settings.ASSISTANT_ENABLED:
                usage.text = DISABLED
            elif not may_use(membership):
                usage.text = NOT_ALLOWED
            elif incoming_count_since(link, timezone.now() - dt.timedelta(hours=1)) > MAX_PER_HOUR:
                usage.text = TOO_MANY
            elif incoming.kind != MessageKind.TEXT or not incoming.text.strip():
                usage.text = TEXT_ONLY
            else:
                history = recent_messages(link, before_id=incoming.pk)
                usage = agent.reply(membership=membership, history=history, text=incoming.text)
            sent_id = whatsapp.send_text(link.phone, usage.text)
        except (anthropic.APIError, WhatsAppError):
            logger.exception("WhatsApp assistant: message %s not answered", message_id)
            usage = agent.AgentReply(text=TECHNICAL)
            try:
                sent_id = whatsapp.send_text(link.phone, TECHNICAL)
            except WhatsAppError:
                logger.exception("WhatsApp assistant: apology to message %s not sent", message_id)
                return
        services.record_outgoing(
            link=link,
            text=usage.text,
            wa_message_id=sent_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
        )


@shared_task(name="assistant.refuse_number")  # type: ignore[untyped-decorator]
def refuse_number(phone: str) -> None:
    """Tell a number linked to nobody that it may not use the assistant. Nothing about it is stored."""
    if not cache.add(f"assistant:refused:{phone}", True, REFUSAL_EVERY):
        return
    try:
        get_client().send_text(phone, NOT_ALLOWED)
    except WhatsAppError:
        logger.exception("WhatsApp assistant: refusal not sent")
