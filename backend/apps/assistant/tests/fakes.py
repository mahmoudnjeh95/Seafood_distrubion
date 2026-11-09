"""Stand-ins for Claude and WhatsApp: tests never leave the machine."""

from types import SimpleNamespace
from typing import Any


def text_block(text: str) -> SimpleNamespace:
    return SimpleNamespace(type="text", text=text)


def tool_call(name: str, arguments: dict[str, Any], call_id: str = "call-1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", name=name, input=arguments, id=call_id)


def response(*blocks: SimpleNamespace, stop_reason: str = "end_turn") -> SimpleNamespace:
    usage = SimpleNamespace(input_tokens=100, output_tokens=20, cache_read_input_tokens=50)
    return SimpleNamespace(content=list(blocks), stop_reason=stop_reason, usage=usage)


class FakeClaude:
    """Answers with the scripted responses in order, and keeps every request."""

    def __init__(self, *responses: SimpleNamespace) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.beta = SimpleNamespace(messages=SimpleNamespace(create=self.create))

    def create(self, **request: Any) -> SimpleNamespace:
        self.requests.append(request)
        return self.responses.pop(0)


class FakeWhatsApp:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []

    def send_text(self, to: str, text: str) -> str:
        self.sent.append((to, text))
        return f"wamid.out.{len(self.sent)}"
