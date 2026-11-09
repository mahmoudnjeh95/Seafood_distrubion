"""The WhatsApp Cloud API client (P12-T01). No call leaves the test: httpx.MockTransport answers."""

import hashlib
import hmac
import json

import httpx
import pytest

from apps.assistant.whatsapp import GraphWhatsAppClient, WhatsAppError, verify_signature

SECRET = "app-secret"
BODY = b'{"object":"whatsapp_business_account"}'


def signature(body: bytes, secret: str = SECRET) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def test_signature_valid():
    assert verify_signature(BODY, signature(BODY), SECRET)


def test_signature_wrong():
    assert not verify_signature(BODY, signature(BODY, "other"), SECRET)
    assert not verify_signature(BODY + b" ", signature(BODY), SECRET)


def test_signature_missing_or_no_secret():
    assert not verify_signature(BODY, None, SECRET)
    assert not verify_signature(BODY, "", SECRET)
    assert not verify_signature(BODY, signature(BODY, ""), "")


@pytest.fixture
def graph(settings):
    settings.WHATSAPP_GRAPH_VERSION = "v23.0"
    settings.WHATSAPP_PHONE_NUMBER_ID = "12345"
    settings.WHATSAPP_ACCESS_TOKEN = "token"
    sent: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, json={"messages": [{"id": f"wamid.{len(sent)}"}]})

    return GraphWhatsAppClient(transport=httpx.MockTransport(answer)), sent


def test_send_text_payload_and_url(graph):
    client, sent = graph
    assert client.send_text("21622123456", "Salam") == "wamid.1"
    request = sent[0]
    assert str(request.url) == "https://graph.facebook.com/v23.0/12345/messages"
    assert request.headers["Authorization"] == "Bearer token"
    assert json.loads(request.content) == {
        "messaging_product": "whatsapp",
        "to": "21622123456",
        "type": "text",
        "text": {"body": "Salam"},
    }


def test_long_text_is_sent_in_two_messages(graph):
    client, sent = graph
    client.send_text("21622123456", "a" * 5000)
    bodies = [json.loads(request.content)["text"]["body"] for request in sent]
    assert len(bodies) == 2
    assert "".join(bodies) == "a" * 5000
    assert all(len(body) <= 4000 for body in bodies)


def test_refused_message_raises(settings):
    settings.WHATSAPP_PHONE_NUMBER_ID = "12345"
    client = GraphWhatsAppClient(transport=httpx.MockTransport(lambda request: httpx.Response(400, json={})))
    with pytest.raises(WhatsAppError):
        client.send_text("21622123456", "Salam")
