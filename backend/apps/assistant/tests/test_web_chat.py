"""The "Assistant IA" screen (D-310): the same assistant as on WhatsApp, without a phone."""

import httpx
import pytest
from rest_framework.test import APIClient

from apps.assistant import agent, speech, tasks
from apps.assistant.models import AssistantMessage, Channel, Direction
from apps.assistant.tests.factories import WhatsAppLinkFactory
from apps.assistant.tests.fakes import FakeWhatsApp
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db

CHAT = "/api/v1/assistant/chat"
MESSAGES = "/api/v1/assistant/chat/messages"


def client_of(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def owner():
    return MembershipFactory.create(role=Role.OWNER)


@pytest.fixture
def queued(monkeypatch):
    handled: list[int] = []
    monkeypatch.setattr(tasks.handle_message, "delay", handled.append)
    return handled


@pytest.fixture
def claude(monkeypatch, settings):
    settings.ASSISTANT_ENABLED = True
    calls = []

    def answer(*, membership, history, text, spoken=False):
        calls.append({"history": [message.text for message in history], "text": text, "spoken": spoken})
        return agent.AgentReply(text="عندك 12 كيلو", input_tokens=900, output_tokens=30)

    monkeypatch.setattr(agent, "reply", answer)
    return calls


def test_a_question_is_stored_and_handed_to_the_worker(owner, queued):
    answer = client_of(owner).post(MESSAGES, {"text": "  chnowa 3andi f frigo?  ", "spoken": True}, format="json")
    assert answer.status_code == 201
    stored = AssistantMessage.objects.get()
    assert (stored.channel, stored.direction, stored.text, stored.spoken) == (
        Channel.WEB,
        Direction.IN,
        "chnowa 3andi f frigo?",
        True,
    )
    assert (stored.membership, stored.link, stored.organization) == (owner, None, owner.organization)
    assert queued == [stored.pk]
    assert answer.json()["id"] == stored.pk


def test_an_empty_question_is_refused(owner, queued):
    assert client_of(owner).post(MESSAGES, {"text": "   "}, format="json").status_code == 400
    assert queued == []


@pytest.mark.parametrize("role", [Role.MANAGER, Role.ACCOUNTANT, Role.DRIVER])
def test_only_the_owner_uses_the_screen(role, queued):
    client = client_of(MembershipFactory.create(role=role))
    assert client.get(CHAT).status_code == 403
    assert client.post(MESSAGES, {"text": "salam"}, format="json").status_code == 403
    assert queued == []


def test_the_answer_is_stored_without_whatsapp(owner, claude, monkeypatch):
    whatsapp = FakeWhatsApp()
    monkeypatch.setattr(tasks, "get_client", lambda: whatsapp)
    question = AssistantMessage.objects.create(
        organization=owner.organization,
        membership=owner,
        channel=Channel.WEB,
        direction=Direction.IN,
        text="chnowa 3andi?",
        spoken=True,
    )
    tasks.handle_message(question.pk)
    assert whatsapp.sent == []
    out = AssistantMessage.objects.get(direction=Direction.OUT)
    assert (out.channel, out.membership, out.link, out.text, out.spoken) == (
        Channel.WEB,
        owner,
        None,
        "عندك 12 كيلو",
        True,
    )
    assert (out.input_tokens, out.output_tokens) == (900, 30)
    assert claude == [{"history": [], "text": "chnowa 3andi?", "spoken": True}]


def test_the_screen_and_whatsapp_keep_their_own_conversations(owner, claude, monkeypatch):
    monkeypatch.setattr(tasks, "get_client", FakeWhatsApp)
    link = WhatsAppLinkFactory.create(membership=owner, organization=owner.organization)
    AssistantMessage.objects.create(
        organization=owner.organization, membership=owner, link=link, direction=Direction.IN, text="on whatsapp"
    )
    for text in ("first", "second"):
        tasks.handle_message(
            AssistantMessage.objects.create(
                organization=owner.organization,
                membership=owner,
                channel=Channel.WEB,
                direction=Direction.IN,
                text=text,
            ).pk
        )
    assert claude[1]["history"] == ["first", "عندك 12 كيلو"]
    body = client_of(owner).get(CHAT).json()
    assert [message["text"] for message in body["messages"]] == ["first", "عندك 12 كيلو", "second", "عندك 12 كيلو"]
    assert [message["direction"] for message in body["messages"]] == ["in", "out", "in", "out"]


def test_the_screen_says_whether_the_assistant_and_the_server_voice_are_on(owner, settings):
    settings.ASSISTANT_ENABLED = False
    settings.AZURE_SPEECH_KEY = ""
    assert client_of(owner).get(CHAT).json() == {"enabled": False, "server_voice": False, "messages": []}
    settings.ASSISTANT_ENABLED = True
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"
    body = client_of(owner).get(CHAT).json()
    assert (body["enabled"], body["server_voice"]) == (True, True)


def test_nobody_sees_another_persons_conversation(owner):
    other = MembershipFactory.create(role=Role.OWNER)
    AssistantMessage.objects.create(
        organization=other.organization, membership=other, channel=Channel.WEB, direction=Direction.IN, text="secret"
    )
    assert client_of(owner).get(CHAT).json()["messages"] == []


# ---- The answer read aloud ----


def answer_of(membership, text="عندك 12 كيلو"):
    return AssistantMessage.objects.create(
        organization=membership.organization,
        membership=membership,
        channel=Channel.WEB,
        direction=Direction.OUT,
        text=text,
    )


def speech_url(message):
    return f"{MESSAGES}/{message.pk}/speech"


@pytest.fixture
def azure(monkeypatch, settings):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"
    read: list[str] = []

    def synthesize(text):
        read.append(text)
        return b"mp3-bytes"

    monkeypatch.setattr(speech, "synthesize", synthesize)
    return read


def test_an_answer_is_read_aloud(owner, azure):
    answer = client_of(owner).get(speech_url(answer_of(owner)))
    assert (answer.status_code, answer["Content-Type"], answer.content) == (200, "audio/mpeg", b"mp3-bytes")
    assert azure == ["عندك 12 كيلو"]


def test_only_ones_own_answers_are_read(owner, azure):
    other = MembershipFactory.create(role=Role.OWNER)
    question = AssistantMessage.objects.create(
        organization=owner.organization, membership=owner, channel=Channel.WEB, direction=Direction.IN, text="q"
    )
    assert client_of(owner).get(speech_url(answer_of(other))).status_code == 404
    assert client_of(owner).get(speech_url(question)).status_code == 404
    assert azure == []


def test_no_server_voice_without_the_key(owner, settings):
    settings.AZURE_SPEECH_KEY = ""
    assert client_of(owner).get(speech_url(answer_of(owner))).status_code == 404


def test_a_failure_of_the_voice_is_not_a_crash(owner, settings, monkeypatch):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"

    def fail(text):
        raise speech.SpeechError("401")

    monkeypatch.setattr(speech, "synthesize", fail)
    assert client_of(owner).get(speech_url(answer_of(owner))).status_code == 502


def test_the_tunisian_voice_reads_arabic_letters_and_the_french_one_the_rest(settings):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "key", "francecentral"
    settings.ASSISTANT_VOICE_AR, settings.ASSISTANT_VOICE_FR = "ar-TN-ReemNeural", "fr-FR-DeniseNeural"
    sent: list[httpx.Request] = []

    def azure(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(200, content=b"mp3")

    transport = httpx.MockTransport(azure)
    assert speech.synthesize("**عندك** 12 كيلو <قرعون>", transport=transport) == b"mp3"
    assert speech.synthesize("- Vous avez 12 kg", transport=transport) == b"mp3"
    arabic, french = (request.content.decode() for request in sent)
    assert str(sent[0].url) == "https://francecentral.tts.speech.microsoft.com/cognitiveservices/v1"
    assert sent[0].headers["Ocp-Apim-Subscription-Key"] == "key"
    assert 'xml:lang="ar-TN"' in arabic
    assert 'name="ar-TN-ReemNeural"' in arabic
    assert ">عندك 12 كيلو &lt;قرعون&gt;</voice>" in arabic
    assert 'name="fr-FR-DeniseNeural"' in french
    assert ">Vous avez 12 kg</voice>" in french


def test_azure_refusing_is_a_speech_error(settings):
    settings.AZURE_SPEECH_KEY, settings.AZURE_SPEECH_REGION = "bad", "francecentral"
    transport = httpx.MockTransport(lambda request: httpx.Response(401, text="denied"))
    with pytest.raises(speech.SpeechError):
        speech.synthesize("salut", transport=transport)
