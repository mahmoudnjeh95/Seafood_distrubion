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
from .selectors import conversation_of, incoming_count_since, recent_messages
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
    """Answer one received message. Messages of one conversation are answered one after the other.

    A WhatsApp message is answered on WhatsApp. One of the "Assistant IA" screen (D-310) has no phone: its answer
    is only stored, and the screen reads it from the message log."""
    incoming = AssistantMessage.objects.select_related("link", "membership__user", "organization").get(pk=message_id)
    membership = incoming.membership
    phone = incoming.link.phone if incoming.link else None
    conversation = conversation_of(incoming)

    def send(text: str) -> str | None:
        return get_client().send_text(phone, text) if phone else None

    with transaction.atomic():
        lock_until_commit(f"assistant:{incoming.channel}:{incoming.link_id or membership.pk}")
        usage = agent.AgentReply(text="")
        try:
            if not settings.ASSISTANT_ENABLED:
                usage.text = DISABLED
            elif not may_use(membership):
                usage.text = NOT_ALLOWED
            elif incoming_count_since(conversation, timezone.now() - dt.timedelta(hours=1)) > MAX_PER_HOUR:
                usage.text = TOO_MANY
            elif incoming.kind != MessageKind.TEXT or not incoming.text.strip():
                usage.text = TEXT_ONLY
            else:
                history = recent_messages(conversation, before_id=incoming.pk)
                usage = agent.reply(membership=membership, history=history, text=incoming.text, spoken=incoming.spoken)
            sent_id = send(usage.text)
        except (anthropic.APIError, WhatsAppError):
            logger.exception("Assistant: message %s not answered", message_id)
            usage = agent.AgentReply(text=TECHNICAL)
            try:
                sent_id = send(TECHNICAL)
            except WhatsAppError:
                logger.exception("Assistant: apology to message %s not sent", message_id)
                return
        services.record_outgoing(
            incoming=incoming,
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
