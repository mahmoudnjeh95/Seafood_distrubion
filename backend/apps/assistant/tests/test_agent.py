"""The conversation loop with Claude (P12-T01), on a scripted fake client."""

import pytest

from apps.assistant import agent, tools
from apps.assistant.models import AssistantMessage, Direction
from apps.assistant.prompt import SYSTEM_PROMPT
from apps.assistant.tests.factories import WhatsAppLinkFactory
from apps.assistant.tests.fakes import FakeClaude, response, text_block, tool_call
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def owner():
    return MembershipFactory.create(role=Role.OWNER)


def test_tool_then_answer(owner, monkeypatch):
    ran = []

    def run_tool(membership, name, args):
        ran.append((name, args))
        return '{"balance":"360.000"}'

    monkeypatch.setattr(agent, "run_tool", run_tool)
    claude = FakeClaude(
        response(tool_call("customer_balance", {"customer_id": 7}), stop_reason="tool_use"),
        response(text_block("Mohamed ysalek 360,000 DT")),
    )
    answer = agent.reply(membership=owner, history=[], text="9addech ysalni Mohamed?", client=claude)
    assert answer.text == "Mohamed ysalek 360,000 DT"
    assert ran == [("customer_balance", {"customer_id": 7})]
    result = claude.requests[1]["messages"][-1]["content"][0]
    assert result == {"type": "tool_result", "tool_use_id": "call-1", "content": '{"balance":"360.000"}'}
    assert answer.input_tokens == 200
    assert answer.output_tokens == 40
    assert answer.cache_read_tokens == 100


def test_request_shape(owner):
    claude = FakeClaude(response(text_block("Salam")))
    agent.reply(membership=owner, history=[], text="salam", client=claude)
    request = claude.requests[0]
    assert request["system"] == SYSTEM_PROMPT
    assert request["model"] == "claude-sonnet-5-5"
    assert {tool["name"] for tool in request["tools"]} == {tool.name for tool in tools.tools_for(owner)}
    assert all(tool["strict"] for tool in request["tools"])
    first = request["messages"][0]
    assert first["role"] == "user"
    assert first["content"].startswith("[Contexte]")
    assert first["content"].endswith("salam")


def test_seventh_tool_round_not_run(owner, monkeypatch):
    ran = []

    def run_tool(membership, name, args):
        ran.append(name)
        return "[]"

    monkeypatch.setattr(agent, "run_tool", run_tool)
    endless = [
        response(tool_call("stock_overview", {}), stop_reason="tool_use") for _ in range(agent.MAX_TOOL_ROUNDS + 1)
    ]
    answer = agent.reply(membership=owner, history=[], text="stock?", client=FakeClaude(*endless))
    assert len(ran) == agent.MAX_TOOL_ROUNDS
    assert answer.text == agent.NO_ANSWER


def test_refusal_gives_the_apology(owner):
    claude = FakeClaude(response(stop_reason="refusal"))
    assert agent.reply(membership=owner, history=[], text="…", client=claude).text == agent.APOLOGY


def test_history_alternates_and_starts_with_the_user(owner):
    link = WhatsAppLinkFactory.create(membership=owner)
    past = [
        AssistantMessage.objects.create(organization=link.organization, link=link, direction=Direction.OUT, text="a"),
        AssistantMessage.objects.create(organization=link.organization, link=link, direction=Direction.IN, text="b"),
        AssistantMessage.objects.create(organization=link.organization, link=link, direction=Direction.IN, text="c"),
    ]
    claude = FakeClaude(response(text_block("ok")))
    agent.reply(membership=owner, history=past, text="d", client=claude)
    turns = claude.requests[0]["messages"]
    assert [turn["role"] for turn in turns] == ["user", "assistant", "user"]
    assert turns[2]["content"] == "b\nc\nd"
