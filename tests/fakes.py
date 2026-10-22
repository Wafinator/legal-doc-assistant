"""Test doubles and builders for the LLM layer.

FakeLLMClient satisfies the LLMClient protocol, so it can stand in for the
real client anywhere. You script what each turn returns, and it records
what it was called with so tests can assert on it afterwards.
"""

import copy
from collections.abc import Iterator
from typing import Any

import anthropic
import httpx2

from app.llm.client import LLMResponse, StreamEvent, TextDelta, Usage

Turn = list[StreamEvent] | Exception


class FakeLLMClient:
    """Plays back one scripted turn per call to stream_turn.

    Each turn is either a list of events to yield, or an exception to raise.
    An exception placed *inside* an event list is raised at that point in the
    stream, which simulates a failure partway through a response.
    """

    def __init__(self, turns: list[Turn]) -> None:
        self._turns = list(turns)
        self.calls: list[dict[str, Any]] = []

    def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Iterator[StreamEvent]:
        # Deep copy: the agent loop keeps appending to `messages`, and we want
        # a snapshot of what this particular call saw.
        self.calls.append({"system": system, "messages": copy.deepcopy(messages), "tools": tools})
        if not self._turns:
            raise AssertionError("FakeLLMClient ran out of scripted turns")
        turn = self._turns.pop(0)
        if isinstance(turn, Exception):
            raise turn
        for event in turn:
            if isinstance(event, Exception):
                raise event
            yield event


def text_turn(*chunks: str, input_tokens: int = 10, output_tokens: int = 5) -> list[StreamEvent]:
    """A turn where the model answers in text: one TextDelta per chunk, then end_turn."""
    return [
        *(TextDelta(c) for c in chunks),
        LLMResponse(
            content=[{"type": "text", "text": "".join(chunks)}],
            stop_reason="end_turn",
            usage=Usage(input_tokens, output_tokens),
        ),
    ]


def tool_turn(
    name: str,
    tool_input: dict[str, Any],
    tool_use_id: str = "toolu_1",
    input_tokens: int = 10,
    output_tokens: int = 5,
) -> list[StreamEvent]:
    """A turn where the model asks to call one tool."""
    return [
        LLMResponse(
            content=[{"type": "tool_use", "id": tool_use_id, "name": name, "input": tool_input}],
            stop_reason="tool_use",
            usage=Usage(input_tokens, output_tokens),
        )
    ]


# Building real SDK exceptions: they need an httpx2 Response (with a Request),
# because the SDK reads status codes and headers off it.

_STATUS_ERRORS: dict[int, type[anthropic.APIStatusError]] = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    409: anthropic.ConflictError,
    429: anthropic.RateLimitError,
    529: anthropic.OverloadedError,
}

_REQUEST = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def make_status_error(
    status_code: int, headers: dict[str, str] | None = None
) -> anthropic.APIStatusError:
    """e.g. make_status_error(429, {"retry-after": "2"}) gives a RateLimitError."""
    response = httpx2.Response(status_code, headers=headers, request=_REQUEST)
    if status_code in _STATUS_ERRORS:
        cls = _STATUS_ERRORS[status_code]
    elif status_code >= 500:
        cls = anthropic.InternalServerError
    else:
        cls = anthropic.APIStatusError
    return cls(f"HTTP {status_code}", response=response, body=None)


def make_connection_error() -> anthropic.APIConnectionError:
    return anthropic.APIConnectionError(request=_REQUEST)


def make_timeout_error() -> anthropic.APITimeoutError:
    return anthropic.APITimeoutError(request=_REQUEST)
