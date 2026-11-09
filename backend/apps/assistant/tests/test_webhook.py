"""Meta's WhatsApp webhook (P12-T01)."""

import hashlib
import hmac
import json

import pytest
from rest_framework.test import APIClient

from apps.assistant import tasks
from apps.assistant.models import AssistantMessage, MessageKind
from apps.assistant.tests.factories import WhatsAppLinkFactory

pytestmark = pytest.mark.django_db

URL = "/api/v1/whatsapp/webhook"
SECRET = "app-secret"


@pytest.fixture(autouse=True)
def meta(settings):
    settings.WHATSAPP_APP_SECRET = SECRET
    settings.WHATSAPP_VERIFY_TOKEN = "verify-me"


@pytest.fixture
def queued(monkeypatch):
    handled: list[int] = []
    refused: list[str] = []
    monkeypatch.setattr(tasks.handle_message, "delay", handled.append)
    monkeypatch.setattr(tasks.refuse_number, "delay", refused.append)
    return handled, refused


def post(payload, secret=SECRET):
    body = json.dumps(payload).encode()
    header = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return APIClient().post(URL, body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=header)


def webhook(*messages, statuses=None):
    value = {"messaging_product": "whatsapp", "messages": list(messages)}
    if statuses is not None:
        value = {"messaging_product": "whatsapp", "statuses": statuses}
    return {"object": "whatsapp_business_account", "entry": [{"changes": [{"field": "messages", "value": value}]}]}


def text(phone, wa_id, body="chnowa 3andi f frigo?"):
    return {"from": phone, "id": wa_id, "type": "text", "text": {"body": body}}


def test_verification_echoes_the_challenge():
    answer = APIClient().get(URL, {"hub.mode": "subscribe", "hub.verify_token": "verify-me", "hub.challenge": "42"})
    assert answer.status_code == 200
    assert answer.content == b"42"


def test_verification_with_wrong_token():
    answer = APIClient().get(URL, {"hub.mode": "subscribe", "hub.verify_token": "nope", "hub.challenge": "42"})
    assert answer.status_code == 403


def test_verification_refused_when_no_token_configured(settings):
    settings.WHATSAPP_VERIFY_TOKEN = ""
    answer = APIClient().get(URL, {"hub.mode": "subscribe", "hub.verify_token": "", "hub.challenge": "42"})
    assert answer.status_code == 403


def test_bad_signature_refused(queued):
    link = WhatsAppLinkFactory.create(phone="21622123456")
    answer = post(webhook(text(link.phone, "wamid.1")), secret="forged")
    assert answer.status_code == 403
    assert AssistantMessage.objects.count() == 0
    assert queued == ([], [])


def test_message_stored_and_handled_once_when_delivered_twice(queued):
    link = WhatsAppLinkFactory.create(phone="21622123456")
    payload = webhook(text(link.phone, "wamid.1"))
    assert post(payload).status_code == 200
    assert post(payload).status_code == 200
    stored = AssistantMessage.objects.get()
    assert stored.text == "chnowa 3andi f frigo?"
    assert stored.link == link
    assert queued == ([stored.pk], [])


def test_status_callbacks_ignored(queued):
    answer = post(webhook(statuses=[{"id": "wamid.1", "status": "delivered"}]))
    assert answer.status_code == 200
    assert AssistantMessage.objects.count() == 0
    assert queued == ([], [])


def test_unknown_number_is_refused_and_nothing_stored(queued):
    answer = post(webhook(text("21699999999", "wamid.9")))
    assert answer.status_code == 200
    assert AssistantMessage.objects.count() == 0
    assert queued == ([], ["21699999999"])


def test_voice_note_stored_as_audio(queued):
    link = WhatsAppLinkFactory.create(phone="21622123456")
    post(webhook({"from": link.phone, "id": "wamid.2", "type": "audio", "audio": {"id": "media-1"}}))
    stored = AssistantMessage.objects.get()
    assert stored.kind == MessageKind.AUDIO
    assert queued[0] == [stored.pk]


def test_unreadable_body_still_answers_200(queued):
    body = b"not json"
    header = "sha256=" + hmac.new(SECRET.encode(), body, hashlib.sha256).hexdigest()
    answer = APIClient().post(URL, body, content_type="application/json", HTTP_X_HUB_SIGNATURE_256=header)
    assert answer.status_code == 200
    assert queued == ([], [])
