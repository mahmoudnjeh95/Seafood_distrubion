"""The conversation with Claude: one user message in, one answer out, with read tools in between."""

from dataclasses import dataclass
from typing import Any

import anthropic
from django.conf import settings
from django.utils import timezone

from apps.core.models import Membership

from .models import AssistantMessage, Direction
from .prompt import SPOKEN_LINE, SYSTEM_PROMPT, context_line
from .tools import run_tool, tools_for

MAX_TOOL_ROUNDS = 6
MAX_TOKENS = 4000
FALLBACK_BETA = "server-side-fallback-2026-07-01"
APOLOGY = "Désolé, je ne peux pas répondre à cette demande."
NO_ANSWER = "Désolé, je n'ai pas trouvé de réponse. Reformulez votre question."


@dataclass
class AgentReply:
    text: str
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0


def get_client() -> Any:
    return anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY or None, max_retries=2, timeout=60)


def _conversation(
    membership: Membership, history: list[AssistantMessage], text: str, spoken: bool = False
) -> list[dict[str, Any]]:
    """The past messages as alternating turns, then the new one, after a line saying who writes and when."""
    user = membership.user
    header = context_line(
        name=user.get_full_name() or user.username,
        role=membership.get_role_display(),
        today=timezone.localdate().isoformat(),
    )
    turns: list[dict[str, Any]] = []
    for message in [*history, None]:
        role = "user" if message is None or message.direction == Direction.IN else "assistant"
        content = text if message is None else (message.text or "…")
        if turns and turns[-1]["role"] == role:
            turns[-1]["content"] += "\n" + content
        else:
            turns.append({"role": role, "content": content})
    if turns[0]["role"] == "assistant":
        turns.insert(0, {"role": "user", "content": "…"})
    turns[0]["content"] = header + "\n" + turns[0]["content"]
    if spoken:
        turns[-1]["content"] += "\n" + SPOKEN_LINE
    return turns


def reply(
    *,
    membership: Membership,
    history: list[AssistantMessage],
    text: str,
    spoken: bool = False,
    client: Any = None,
) -> AgentReply:
    """Answer one message. `history` is the conversation before it (selectors.recent_messages); `spoken`: the
    answer is read aloud."""
    client = client or get_client()
    tools = [tool.definition() for tool in tools_for(membership)]
    messages = _conversation(membership, history, text, spoken)
    usage = AgentReply(text="")
    for round_number in range(MAX_TOOL_ROUNDS + 1):
        response = client.beta.messages.create(
            model=settings.ASSISTANT_MODEL,
            max_tokens=MAX_TOKENS,
            system=SYSTEM_PROMPT,
            tools=tools,
            messages=messages,
            output_config={"effort": "low"},
            cache_control={"type": "ephemeral"},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        )
        _add_usage(usage, response)
        if response.stop_reason == "refusal":
            usage.text = APOLOGY
            return usage
        calls = [block for block in response.content if block.type == "tool_use"]
        if response.stop_reason == "pause_turn":
            messages.append({"role": "assistant", "content": response.content})
            continue
        if not calls or round_number == MAX_TOOL_ROUNDS:
            usage.text = _text_of(response) or NO_ANSWER
            return usage
        messages.append({"role": "assistant", "content": response.content})
        messages.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": run_tool(membership, call.name, call.input),
                    }
                    for call in calls
                ],
            }
        )
    usage.text = NO_ANSWER
    return usage


def _text_of(response: Any) -> str:
    return "\n".join(block.text for block in response.content if block.type == "text").strip()


def _add_usage(total: AgentReply, response: Any) -> None:
    used = getattr(response, "usage", None)
    if used is None:
        return
    total.input_tokens += getattr(used, "input_tokens", 0) or 0
    total.output_tokens += getattr(used, "output_tokens", 0) or 0
    total.cache_read_tokens += getattr(used, "cache_read_input_tokens", 0) or 0
