import logging
from typing import Any

from django.conf import settings
from django.http import HttpResponse
from drf_spectacular.utils import extend_schema
from rest_framework.exceptions import ParseError
from rest_framework.permissions import AllowAny
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from .. import services, tasks
from ..whatsapp import verify_signature

logger = logging.getLogger(__name__)


def _incoming_messages(payload: Any) -> list[dict[str, Any]]:
    """The user messages of a webhook body; status callbacks (sent, delivered, read) carry none."""
    found: list[dict[str, Any]] = []
    if not isinstance(payload, dict):
        return found
    for entry in payload.get("entry") or []:
        for change in (entry or {}).get("changes") or []:
            value = (change or {}).get("value") or {}
            found.extend(message for message in value.get("messages") or [] if isinstance(message, dict))
    return found


# Meta's WhatsApp webhook (P12-T01). Meta signs each call with the app secret instead of logging in, so no
# session and no CSRF; the signature is checked first. Kept out of the API contract: no front end calls it.
class WhatsAppWebhookView(APIView):
    authentication_classes = ()
    permission_classes = (AllowAny,)

    @extend_schema(exclude=True)
    def get(self, request: Request) -> HttpResponse:
        """Meta's one-time check when the webhook address is saved: echo the challenge if the token matches."""
        token = settings.WHATSAPP_VERIFY_TOKEN
        if (
            token
            and request.query_params.get("hub.mode") == "subscribe"
            and request.query_params.get("hub.verify_token") == token
        ):
            return HttpResponse(request.query_params.get("hub.challenge", ""), content_type="text/plain")
        return HttpResponse(status=403)

    @extend_schema(exclude=True)
    def post(self, request: Request) -> Response:
        body = request.body
        if not verify_signature(body, request.headers.get("X-Hub-Signature-256"), settings.WHATSAPP_APP_SECRET):
            return Response(status=403)
        try:
            messages = _incoming_messages(request.data)
        except ParseError:  # an unreadable body: Meta would send it again and again on anything but 200
            logger.warning("WhatsApp webhook: unreadable body")
            return Response({})
        for message in messages:
            phone = str(message.get("from") or "")
            kind = str(message.get("type") or "")
            text = str((message.get("text") or {}).get("body") or "")
            stored = services.record_incoming(
                phone=phone, wa_message_id=str(message.get("id") or ""), kind=kind, text=text
            )
            if stored is not None:
                tasks.handle_message.delay(stored.pk)
            elif services.is_unknown_number(phone):
                tasks.refuse_number.delay(phone)
        return Response({})
