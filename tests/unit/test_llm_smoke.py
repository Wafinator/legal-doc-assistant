"""Scaffolding smoke test for the LLM layer: proves the fake and the error
builders work. Your retry tests go in tests/unit/test_retry.py."""

import anthropic

from app.llm.client import LLMResponse, TextDelta
from tests.fakes import FakeLLMClient, make_status_error, text_turn


def test_fake_plays_back_a_scripted_turn():
    fake = FakeLLMClient([text_turn("Hello, ", "world")])

    events = list(fake.stream_turn(system="s", messages=[], tools=[]))

    assert events[:2] == [TextDelta("Hello, "), TextDelta("world")]
    assert isinstance(events[-1], LLMResponse)
    assert len(fake.calls) == 1


def test_make_status_error_builds_the_right_sdk_class():
    error = make_status_error(429, {"retry-after": "2"})

    assert isinstance(error, anthropic.RateLimitError)
    assert error.status_code == 429
    assert error.response.headers["retry-after"] == "2"
