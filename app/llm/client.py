"""The LLM boundary: one interface, one real implementation.

Everything else in the app (the agent loop, the SSE endpoint) depends only on the
`LLMClient` protocol, never on the Anthropic SDK directly. Tests pass in a fake
that satisfies the same protocol, so they run offline with no API key.
"""

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, Protocol

import anthropic

from app.config import Settings, get_settings
from app.llm.retry import RetryPolicy, stream_with_retries

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextDelta:
    """A chunk of answer text, forwarded to the user as soon as it arrives."""

    text: str


@dataclass(frozen=True)
class Usage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    """The complete result of one model turn.

    `content` is the list of content blocks as plain dicts: text, tool_use, and
    thinking blocks with their signatures. The agent loop sends it back
    unchanged as the assistant message on the next turn, which the API requires
    for thinking blocks.
    """

    content: list[dict[str, Any]]
    stop_reason: str | None
    usage: Usage


StreamEvent = TextDelta | LLMResponse


class LLMClient(Protocol):
    """Like a C# interface. Any class with a matching `stream_turn` method
    satisfies it; no explicit "implements" declaration is needed."""

    def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Iterator[StreamEvent]:
        """Yield zero or more TextDelta events, then exactly one LLMResponse, last."""
        ...


class AnthropicLLMClient:
    def __init__(self, client: anthropic.Anthropic, settings: Settings) -> None:
        self._client = client
        self._settings = settings
        self._policy = RetryPolicy(
            max_attempts=settings.llm_max_attempts,
            base_delay=settings.llm_retry_base_delay,
            max_delay=settings.llm_retry_max_delay,
        )

    def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Iterator[StreamEvent]:
        attempts = 0
        started = time.perf_counter()

        def open_stream() -> Iterator[StreamEvent]:
            nonlocal attempts  # lets this inner function update the outer counter
            attempts += 1
            with self._client.messages.stream(
                model=self._settings.llm_model,
                max_tokens=self._settings.llm_max_tokens,
                system=system,
                messages=messages,
                tools=tools,
                output_config={"effort": self._settings.llm_effort},
            ) as stream:
                for event in stream:
                    if event.type == "text":
                        yield TextDelta(event.text)
                message = stream.get_final_message()
            yield LLMResponse(
                content=[
                    block.model_dump(mode="json", exclude_none=True) for block in message.content
                ],
                stop_reason=message.stop_reason,
                usage=Usage(message.usage.input_tokens, message.usage.output_tokens),
            )

        try:
            for event in stream_with_retries(open_stream, self._policy):
                if isinstance(event, LLMResponse):
                    log.info(
                        "llm_call",
                        extra={
                            "model": self._settings.llm_model,
                            "attempts": attempts,
                            "latency_ms": _elapsed_ms(started),
                            "input_tokens": event.usage.input_tokens,
                            "output_tokens": event.usage.output_tokens,
                            "stop_reason": event.stop_reason,
                        },
                    )
                yield event
        except Exception as exc:
            log.error(
                "llm_call_failed",
                extra={
                    "model": self._settings.llm_model,
                    "attempts": attempts,
                    "latency_ms": _elapsed_ms(started),
                    "error": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None),
                },
            )
            raise


def _elapsed_ms(started: float) -> int:
    return round((time.perf_counter() - started) * 1000)


PLACEHOLDER_API_KEY = "your-anthropic-api-key"  # the value in .env.example


class LLMNotConfiguredError(Exception):
    """LLM_MODE=anthropic but no usable API key. main.py turns this into a 503."""


@lru_cache
def get_llm_client() -> LLMClient:
    """FastAPI dependency. Built once on first use (not at import), so the app
    and the test suite start fine without an API key. Tests replace it with
    `app.dependency_overrides[get_llm_client] = lambda: FakeLLMClient(...)`."""
    settings = get_settings()
    if settings.llm_mode == "demo":
        from app.llm.demo import DemoLLMClient  # imported here: demo.py imports this module

        log.info("llm_mode", extra={"mode": "demo"})
        return DemoLLMClient()
    api_key = settings.anthropic_api_key.get_secret_value() if settings.anthropic_api_key else ""
    if not api_key.strip() or api_key == PLACEHOLDER_API_KEY:
        # Fail here, before any streaming starts, so the client gets a clear 503
        # instead of a vague error event halfway through a response.
        raise LLMNotConfiguredError(
            "No Anthropic API key configured. Set ANTHROPIC_API_KEY in .env, "
            "or set LLM_MODE=demo to run without one."
        )
    sdk = anthropic.Anthropic(
        api_key=api_key,
        max_retries=0,  # we retry ourselves, so every attempt is logged and tested
        timeout=anthropic.Timeout(settings.llm_read_timeout, connect=settings.llm_connect_timeout),
    )
    return AnthropicLLMClient(sdk, settings)
