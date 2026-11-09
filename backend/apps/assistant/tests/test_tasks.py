"""Answering a received message (P12-T01): who gets an answer, and what happens when something fails."""

import datetime as dt

import anthropic
import pytest
from django.core.cache import cache
from django.utils import timezone

from apps.assistant import agent, tasks
from apps.assistant.models import AssistantMessage, Direction, MessageKind
from apps.assistant.tests.factories import WhatsAppLinkFactory
from apps.assistant.tests.fakes import FakeWhatsApp
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


class Unreachable(anthropic.APIError):
    """Claude's API cannot be reached (the SDK's own errors need a live request to build)."""

    def __init__(self) -> None:
        Exception.__init__(self, "unreachable")


@pytest.fixture
def whatsapp(monkeypatch, settings):
    settings.ASSISTANT_ENABLED = True
    fake = FakeWhatsApp()
    monkeypatch.setattr(tasks, "get_client", lambda: fake)
    return fake


@pytest.fixture
def claude(monkeypatch):
    calls = []

    def answer(*, membership, history, text):
        calls.append({"membership": membership, "history": history, "text": text})
        return agent.AgentReply(text="3andek 12,000 kg", input_tokens=900, output_tokens=30, cache_read_tokens=700)

    monkeypatch.setattr(agent, "reply", answer)
    return calls


def incoming(link, text="chnowa 3andi?", kind=MessageKind.TEXT):
    return AssistantMessage.objects.create(
        organization=link.organization, link=link, direction=Direction.IN, kind=kind, text=text
    )


def test_owner_gets_the_answer_and_it_is_logged(whatsapp, claude):
    link = WhatsAppLinkFactory.create(phone="21622123456")
    tasks.handle_message(incoming(link).pk)
    assert whatsapp.sent == [("21622123456", "3andek 12,000 kg")]
    out = AssistantMessage.objects.get(direction=Direction.OUT)
    assert (out.input_tokens, out.output_tokens, out.cache_read_tokens) == (900, 30, 700)
    assert out.wa_message_id == "wamid.out.1"


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ACCOUNTANT, Role.DRIVER])
def test_role_without_the_permission_is_refused_without_ai(whatsapp, claude, role):
    link = WhatsAppLinkFactory.create(membership=MembershipFactory.create(role=role))
    tasks.handle_message(incoming(link).pk)
    assert whatsapp.sent == [(link.phone, tasks.NOT_ALLOWED)]
    assert claude == []


def test_switched_off(whatsapp, claude, settings):
    settings.ASSISTANT_ENABLED = False
    link = WhatsAppLinkFactory.create()
    tasks.handle_message(incoming(link).pk)
    assert whatsapp.sent == [(link.phone, tasks.DISABLED)]
    assert claude == []


def test_too_many_messages_in_an_hour(whatsapp, claude):
    link = WhatsAppLinkFactory.create()
    for _ in range(tasks.MAX_PER_HOUR):
        incoming(link)
    tasks.handle_message(incoming(link).pk)
    assert whatsapp.sent == [(link.phone, tasks.TOO_MANY)]
    assert claude == []


def test_voice_note_gets_text_only_reply(whatsapp, claude):
    link = WhatsAppLinkFactory.create()
    tasks.handle_message(incoming(link, text="", kind=MessageKind.AUDIO).pk)
    assert whatsapp.sent == [(link.phone, tasks.TEXT_ONLY)]
    assert claude == []


def test_ai_failure_sends_the_apology(whatsapp, monkeypatch):
    def broken(**kwargs):
        raise Unreachable

    monkeypatch.setattr(agent, "reply", broken)
    link = WhatsAppLinkFactory.create()
    tasks.handle_message(incoming(link).pk)
    assert whatsapp.sent == [(link.phone, tasks.TECHNICAL)]


def test_history_is_recent_and_excludes_the_new_message(whatsapp, claude):
    link = WhatsAppLinkFactory.create()
    old = incoming(link, text="old")
    AssistantMessage.objects.filter(pk=old.pk).update(created_at=timezone.now() - dt.timedelta(hours=25))
    earlier = incoming(link, text="earlier")
    new = incoming(link, text="new")
    tasks.handle_message(new.pk)
    assert [message.pk for message in claude[0]["history"]] == [earlier.pk]
    assert claude[0]["text"] == "new"


def test_unknown_number_refused_once_a_day(whatsapp):
    cache.clear()
    tasks.refuse_number("21699999999")
    tasks.refuse_number("21699999999")
    assert whatsapp.sent == [("21699999999", tasks.NOT_ALLOWED)]
