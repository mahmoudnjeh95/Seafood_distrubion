"""Meta's WhatsApp Cloud API: check that a webhook really comes from Meta, and send messages."""

import hashlib
import hmac
from typing import Protocol

import httpx
from django.conf import settings

# WhatsApp refuses text bodies over 4 096 characters; a margin keeps a split clear of the limit.
MAX_TEXT = 4000


class WhatsAppError(Exception):
    """Meta refused a message or could not be reached."""


class WhatsAppClient(Protocol):
    def send_text(self, to: str, text: str) -> str | None: ...


def verify_signature(body: bytes, header: str | None, secret: str) -> bool:
    """True when `X-Hub-Signature-256` is the HMAC-SHA256 of the raw body with the app secret."""
    if not header or not secret:
        return False
    expected = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(header, expected)


def split_text(text: str, size: int = MAX_TEXT) -> list[str]:
    """Cut a long answer in pieces WhatsApp accepts, at a line break when there is one."""
    pieces: list[str] = []
    rest = text
    while len(rest) > size:
        cut = rest.rfind("\n", 0, size)
        if cut <= 0:
            cut = size
        pieces.append(rest[:cut])
        rest = rest[cut:].lstrip("\n")
    pieces.append(rest)
    return pieces


class GraphWhatsAppClient:
    def __init__(self, transport: httpx.BaseTransport | None = None) -> None:
        self.url = (
            f"https://graph.facebook.com/{settings.WHATSAPP_GRAPH_VERSION}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
        )
        self.http = httpx.Client(
            transport=transport,
            timeout=15,
            headers={"Authorization": f"Bearer {settings.WHATSAPP_ACCESS_TOKEN}"},
        )

    def send_text(self, to: str, text: str) -> str | None:
        """Send `text` (split when long); returns WhatsApp's id of the last piece."""
        message_id: str | None = None
        for piece in split_text(text):
            payload = {"messaging_product": "whatsapp", "to": to, "type": "text", "text": {"body": piece}}
            try:
                response = self.http.post(self.url, json=payload)
            except httpx.HTTPError as error:
                raise WhatsAppError(repr(error)) from error
            if response.status_code >= 300:
                raise WhatsAppError(f"{response.status_code}: {response.text[:500]}")
            messages = response.json().get("messages") or [{}]
            message_id = messages[0].get("id")
        return message_id


def get_client() -> WhatsAppClient:
    return GraphWhatsAppClient()
