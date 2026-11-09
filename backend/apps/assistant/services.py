"""Every write of the assistant app (ARCHITECTURE §3): phone links and the message log."""

import re

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core import audit
from apps.core.models import Membership, User

from .models import AssistantMessage, Direction, MessageKind, WhatsAppLink
from .selectors import link_for_phone

TUNISIA_PREFIX = "216"


def normalize_phone(raw: str) -> str:
    """E.164 digits without "+": "+216 22 123 456", "0021622123456" and "22123456" all give "21622123456"."""
    digits = re.sub(r"\D", "", raw or "")
    if digits.startswith("00"):
        digits = digits[2:]
    if len(digits) == 8:
        digits = TUNISIA_PREFIX + digits
    if not 8 <= len(digits) <= 15:
        raise ValueError(f"Numéro de téléphone invalide : {raw!r}")
    return digits


@transaction.atomic
def link_phone(*, membership: Membership, phone: str, actor: User) -> WhatsAppLink:
    """Give a user's WhatsApp number to the assistant, replacing the one they had."""
    number = normalize_phone(phone)
    if WhatsAppLink.objects.filter(phone=number).exclude(membership=membership).exists():
        raise ValidationError("Ce numéro est déjà lié à un autre utilisateur.")
    before = WhatsAppLink.objects.filter(membership=membership).values_list("phone", flat=True).first()
    link, _ = WhatsAppLink.objects.update_or_create(
        membership=membership,
        defaults={"organization": membership.organization, "phone": number, "is_active": True},
    )
    audit.record(
        organization=membership.organization,
        actor=actor,
        action="assistant.phone_linked",
        target=link,
        before={"phone": before} if before else None,
        after={"phone": number},
    )
    return link


@transaction.atomic
def unlink_phone(*, membership: Membership, actor: User) -> None:
    link = WhatsAppLink.objects.filter(membership=membership).first()
    if link is None:
        return
    audit.record(
        organization=membership.organization,
        actor=actor,
        action="assistant.phone_unlinked",
        target=link,
        before={"phone": link.phone},
    )
    link.delete()


def message_kind(whatsapp_type: str) -> str:
    return whatsapp_type if whatsapp_type in MessageKind.values else MessageKind.OTHER


def record_incoming(*, phone: str, wa_message_id: str, kind: str, text: str) -> AssistantMessage | None:
    """Store a message from a linked phone. None when the number is not linked, or when the message is already
    stored (WhatsApp delivers a webhook again when it got no answer in time)."""
    try:
        number = normalize_phone(phone)
    except ValueError:
        return None
    link = link_for_phone(number)
    if link is None:
        return None
    try:
        with transaction.atomic():
            return AssistantMessage.objects.create(
                organization=link.organization,
                link=link,
                direction=Direction.IN,
                wa_message_id=wa_message_id or None,
                kind=message_kind(kind),
                text=text,
            )
    except IntegrityError:
        return None


def is_unknown_number(phone: str) -> bool:
    """A valid number linked to no active user: it gets the refusal, and nothing else."""
    try:
        return link_for_phone(normalize_phone(phone)) is None
    except ValueError:
        return False


@transaction.atomic
def record_outgoing(
    *,
    link: WhatsAppLink,
    text: str,
    wa_message_id: str | None = None,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> AssistantMessage:
    return AssistantMessage.objects.create(
        organization=link.organization,
        link=link,
        direction=Direction.OUT,
        wa_message_id=wa_message_id,
        text=text,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=cache_read_tokens,
    )
