"""Unit tests for the LLM retry helpers."""

import anthropic
import httpx
import pytest

from app.llm.retry import (  
    compute_delay,
    is_retryable,
    retry_after_seconds,
    stream_with_retries,
)

MAX_DELAY = 8.0
MAX_ATTEMPTS = 3

REQUEST = httpx.Request("POST", "https://api.anthropic.com/v1/messages")

ERROR_CLASSES = {
    400: anthropic.BadRequestError,
    401: anthropic.AuthenticationError,
    403: anthropic.PermissionDeniedError,
    404: anthropic.NotFoundError,
    409: anthropic.ConflictError,
    429: anthropic.RateLimitError,
    500: anthropic.InternalServerError,
    503: anthropic.InternalServerError,
    529: anthropic.OverloadedError,
}


def status_error(code, headers=None):
    """Build a real SDK error for a given status code, the same way the client would."""
    cls = ERROR_CLASSES.get(code, anthropic.APIStatusError)
    response = httpx.Response(code, request=REQUEST, headers=headers or {})
    return cls(f"HTTP {code}", response=response, body=None)


def fake_open_stream(outcomes):
    """Return an open_stream stand in plus a call counter.

    Each call pops the next outcome. An exception gets raised, anything else
    is treated as a list of events and returned as an iterator.
    """
    calls = {"count": 0}

    def open_stream():
        calls["count"] += 1
        outcome = outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return iter(outcome)

    return open_stream, calls


def fails_mid_stream(event, error):
    """A stream that yields one event and then blows up."""
    yield event
    raise error


# is_retryable

@pytest.mark.parametrize(
    "error",
    [
        pytest.param(status_error(429), id="429"),
        pytest.param(status_error(529), id="529"),
        pytest.param(status_error(500), id="500"),
        pytest.param(status_error(503), id="503"),
        pytest.param(status_error(408), id="408"),
        pytest.param(status_error(409), id="409"),
        pytest.param(anthropic.APIConnectionError(request=REQUEST), id="connection_error"),
        pytest.param(anthropic.APITimeoutError(request=REQUEST), id="timeout"),
    ],
)
def test_is_retryable_true(error):
    assert is_retryable(error) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_is_retryable_false_for_client_errors(code):
    assert is_retryable(status_error(code)) is False


def test_is_retryable_false_for_unrelated_exception():
    assert is_retryable(ValueError("not an API error")) is False


# compute_delay

@pytest.mark.parametrize("attempt, expected", [(1, 0.5), (2, 1.0), (3, 2.0)])
def test_compute_delay_doubles_each_attempt(attempt, expected):
    assert compute_delay(attempt, max_delay=MAX_DELAY, rand=lambda: 1.0) == expected


def test_compute_delay_is_capped_at_max_delay():
    assert compute_delay(20, max_delay=MAX_DELAY, rand=lambda: 1.0) == MAX_DELAY


def test_compute_delay_zero_jitter_gives_zero():
    assert compute_delay(3, max_delay=MAX_DELAY, rand=lambda: 0.0) == 0


def test_compute_delay_retry_after_overrides_smaller_delay():
    # attempt 1 would normally wait 0.5s, the server asked for 3
    assert compute_delay(1, max_delay=MAX_DELAY, retry_after=3, rand=lambda: 1.0) == 3


def test_compute_delay_retry_after_is_capped_at_max_delay():
    assert compute_delay(1, max_delay=MAX_DELAY, retry_after=60, rand=lambda: 1.0) == MAX_DELAY


# retry_after_seconds

def test_retry_after_seconds_reads_header():
    assert retry_after_seconds(status_error(429, headers={"retry-after": "3"})) == 3


def test_retry_after_seconds_missing_header_returns_none():
    assert retry_after_seconds(status_error(429)) is None


def test_retry_after_seconds_non_numeric_returns_none():
    assert retry_after_seconds(status_error(429, headers={"retry-after": "soon"})) is None


# stream_with_retries

def test_stream_recovers_after_two_overloaded_errors():
    events = ["event_1", "event_2"]
    open_stream, calls = fake_open_stream([status_error(529), status_error(529), events])
    delays = []

    result = list(
        stream_with_retries(
            open_stream,
            max_attempts=MAX_ATTEMPTS,
            sleep=delays.append,
            rand=lambda: 1.0,
        )
    )

    assert result == events
    assert calls["count"] == 3
    assert len(delays) == 2


def test_stream_gives_up_after_max_attempts():
    open_stream, calls = fake_open_stream([status_error(429) for _ in range(MAX_ATTEMPTS)])
    delays = []

    with pytest.raises(anthropic.RateLimitError):
        list(
            stream_with_retries(
                open_stream,
                max_attempts=MAX_ATTEMPTS,
                sleep=delays.append,
                rand=lambda: 1.0,
            )
        )

    assert calls["count"] == MAX_ATTEMPTS


def test_stream_does_not_retry_client_error():
    open_stream, calls = fake_open_stream([status_error(400)])
    delays = []

    with pytest.raises(anthropic.BadRequestError):
        list(
            stream_with_retries(
                open_stream,
                max_attempts=MAX_ATTEMPTS,
                sleep=delays.append,
                rand=lambda: 1.0,
            )
        )

    assert calls["count"] == 1
    assert delays == []


def test_stream_does_not_retry_after_events_were_sent():
    # Once an event reaches the caller, retrying would send duplicate output,
    # so a mid stream failure has to surface instead of starting over.
    open_stream, calls = fake_open_stream([fails_mid_stream("event_1", status_error(529))])
    delays = []
    received = []

    with pytest.raises(anthropic.APIStatusError) as exc_info:
        for event in stream_with_retries(
            open_stream,
            max_attempts=MAX_ATTEMPTS,
            sleep=delays.append,
            rand=lambda: 1.0,
        ):
            received.append(event)

    assert exc_info.value.status_code == 529
    assert calls["count"] == 1
    assert received == ["event_1"]
