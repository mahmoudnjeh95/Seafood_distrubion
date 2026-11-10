"""WhatsApp assistant (Phase 12): which phone belongs to which user, and the messages exchanged."""

from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import Membership, OrganizationScopedModel


class WhatsAppLink(OrganizationScopedModel):
    """One user's WhatsApp number. The assistant only talks to linked numbers of active users."""

    membership = models.OneToOneField(Membership, on_delete=models.CASCADE, related_name="whatsapp_link")
    # E.164 digits without "+", e.g. "21622123456" (services.normalize_phone).
    phone = models.CharField(max_length=20, unique=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self) -> str:
        return f"+{self.phone} · {self.membership.user}"


class Direction(models.TextChoices):
    IN = "in", _("Reçu")
    OUT = "out", _("Envoyé")


class MessageKind(models.TextChoices):
    TEXT = "text", _("Texte")
    AUDIO = "audio", _("Note vocale")
    IMAGE = "image", _("Image")
    OTHER = "other", _("Autre")


class Channel(models.TextChoices):
    WHATSAPP = "whatsapp", _("WhatsApp")
    # The "Assistant IA" screen of the admin app (D-310): the same assistant, typed or spoken in the browser.
    WEB = "web", _("Application")


class AssistantMessage(OrganizationScopedModel):
    """A message received from or sent to a user: the conversation memory and the usage log. Each channel keeps
    its own conversation."""

    membership = models.ForeignKey(Membership, on_delete=models.CASCADE, related_name="assistant_messages")
    channel = models.CharField(max_length=10, choices=Channel.choices, default=Channel.WHATSAPP)
    # The phone of a WhatsApp message; none on a message of the screen.
    link = models.ForeignKey(WhatsAppLink, on_delete=models.CASCADE, related_name="messages", null=True, blank=True)
    direction = models.CharField(max_length=3, choices=Direction.choices)
    # WhatsApp's id of the message: unique, so a webhook delivered twice is handled once.
    wa_message_id = models.CharField(max_length=128, unique=True, null=True, blank=True)
    kind = models.CharField(max_length=10, choices=MessageKind.choices, default=MessageKind.TEXT)
    text = models.TextField(blank=True)
    # Dictated, or its answer is read aloud (screen only): the answer is then written to be spoken.
    spoken = models.BooleanField(default=False)
    # AI usage of an outgoing answer.
    input_tokens = models.PositiveIntegerField(default=0)
    output_tokens = models.PositiveIntegerField(default=0)
    cache_read_tokens = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ("created_at", "id")

    def __str__(self) -> str:
        who = self.link.phone if self.link else str(self.membership.user)
        return f"{self.get_direction_display()} · {who} · {self.created_at:%Y-%m-%d %H:%M}"
