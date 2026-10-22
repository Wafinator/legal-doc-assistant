"""Unit tests for the LLM retry helpers."""

import anthropic
import pytest

from app.llm.retry import (
    RetryPolicy,
    compute_delay,
    is_retryable,
    retry_after_seconds,
    stream_with_retries,
)
from tests.fakes import (
    make_connection_error,
    make_status_error,
    make_timeout_error,
)

MAX_DELAY = 8.0
MAX_ATTEMPTS = 3
POLICY = RetryPolicy(max_attempts=MAX_ATTEMPTS, base_delay=0.5, max_delay=MAX_DELAY)


# is_retryable


@pytest.mark.parametrize(
    "error",
    [
        pytest.param(make_status_error(429), id="429"),
        pytest.param(make_status_error(529), id="529"),
        pytest.param(make_status_error(500), id="500"),
        pytest.param(make_status_error(503), id="503"),
        pytest.param(make_status_error(408), id="408"),
        pytest.param(make_status_error(409), id="409"),
        pytest.param(make_connection_error(), id="connection_error"),
        pytest.param(make_timeout_error(), id="timeout"),
    ],
)
def test_is_retryable_true(error):
    assert is_retryable(error) is True


@pytest.mark.parametrize("code", [400, 401, 403, 404])
def test_is_retryable_false_for_client_errors(code):
    assert is_retryable(make_status_error(code)) is False


def test_is_retryable_false_for_unrelated_exception():
    assert is_retryable(ValueError("not an API error")) is False


# compute_delay


@pytest.mark.parametrize("attempt, expected", [(1, 0.5), (2, 1.0), (3, 2.0)])
def test_compute_delay_doubles_each_attempt(attempt, expected):
    assert compute_delay(attempt, policy=POLICY, rand=lambda: 1.0) == expected


def test_compute_delay_is_capped_at_max_delay():
    assert compute_delay(20, policy=POLICY, rand=lambda: 1.0) == MAX_DELAY


def test_compute_delay_zero_jitter_gives_zero():
    assert compute_delay(3, policy=POLICY, rand=lambda: 0.0) == 0


def test_compute_delay_retry_after_overrides_smaller_delay():
    # attempt 1 would normally wait 0.5s, the server asked for 3
    assert compute_delay(1, policy=POLICY, retry_after=3, rand=lambda: 1.0) == 3


def test_compute_delay_retry_after_is_capped_at_max_delay():
    assert compute_delay(1, policy=POLICY, retry_after=60, rand=lambda: 1.0) == MAX_DELAY


# retry_after_seconds


def test_retry_after_seconds_reads_header():
    assert retry_after_seconds(make_status_error(429, {"retry-after": "3"})) == 3


def test_retry_after_seconds_missing_header_returns_none():
    assert retry_after_seconds(make_status_error(429)) is None


def test_retry_after_seconds_non_numeric_returns_none():
    assert retry_after_seconds(make_status_error(429, {"retry-after": "soon"})) is None


# stream_with_retries


def test_stream_recovers_after_two_overloaded_errors():
    events = ["event_1", "event_2"]
    open_stream, calls = fake_open_stream([make_status_error(529), make_status_error(529), events])
    delays = []

    result = list(
        stream_with_retries(
            open_stream,
            policy=POLICY,
            sleep=delays.append,
        )
    )

    assert result == events
    assert calls["count"] == 3
    assert len(delays) == 2


def test_stream_gives_up_after_max_attempts():
    open_stream, calls = fake_open_stream([make_status_error(429) for _ in range(MAX_ATTEMPTS)])
    delays = []

    with pytest.raises(anthropic.RateLimitError):
        list(
            stream_with_retries(
                open_stream,
                policy=POLICY,
                sleep=delays.append,
            )
        )

    assert calls["count"] == MAX_ATTEMPTS
    assert len(delays) == MAX_ATTEMPTS - 1


def test_stream_does_not_retry_client_error():
    open_stream, calls = fake_open_stream([make_status_error(400)])
    delays = []

    with pytest.raises(anthropic.BadRequestError):
        list(
            stream_with_retries(
                open_stream,
                policy=POLICY,
                sleep=delays.append,
            )
        )

    assert calls["count"] == 1
    assert delays == []


def test_stream_does_not_retry_after_events_were_sent():
    # Once an event reaches the caller, retrying would send duplicate output,
    # so a mid stream failure has to surface instead of starting over.
    open_stream, calls = fake_open_stream([fails_mid_stream("event_1", make_status_error(529))])
    delays = []
    received = []

    with pytest.raises(anthropic.APIStatusError) as exc_info:
        for event in stream_with_retries(
            open_stream,
            policy=POLICY,
            sleep=delays.append,
        ):
            received.append(event)

    assert exc_info.value.status_code == 529
    assert calls["count"] == 1
    assert received == ["event_1"]
    assert delays == []


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
