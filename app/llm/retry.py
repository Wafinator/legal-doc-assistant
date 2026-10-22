"""Retries with exponential backoff and jitter for streaming LLM calls.

Kept free of any SDK client so it can be unit-tested with plain functions:
pass in something that raises, and a fake `sleep` that records delays.
"""

import logging
import random
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import anthropic

log = logging.getLogger(__name__)

# 408 request timeout, 409 conflict, 429 rate limited, 5xx server-side (529 = overloaded).
# Everything else in 4xx means the request itself is wrong; sending it again won't help.
RETRYABLE_STATUS_CODES = frozenset({408, 409, 429})


@dataclass(frozen=True)
class RetryPolicy:
    max_attempts: int = 3
    base_delay: float = 0.5
    max_delay: float = 8.0


def is_retryable(exc: BaseException) -> bool:
    # APITimeoutError is a subclass of APIConnectionError, so timeouts land here too.
    if isinstance(exc, anthropic.APIConnectionError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code in RETRYABLE_STATUS_CODES or exc.status_code >= 500
    return False


def retry_after_seconds(exc: BaseException) -> float | None:
    """The server's own `retry-after` hint (in seconds), if it sent one."""
    if not isinstance(exc, anthropic.APIStatusError):
        return None
    value = exc.response.headers.get("retry-after")
    try:
        return float(value) if value is not None else None
    except ValueError:
        return None  # it can also be an HTTP date; not worth parsing here


def compute_delay(
    attempt: int,
    policy: RetryPolicy,
    retry_after: float | None = None,
    rand: Callable[[], float] = random.random,
) -> float:
    """Seconds to wait after failed attempt number `attempt` (1-based).

    Exponential backoff doubles the ceiling each time (0.5s, 1s, 2s, ...) up to
    max_delay. "Full jitter" then picks a random point between 0 and that ceiling,
    so many clients that failed at the same moment don't all retry at the same moment.
    A retry-after hint from the server wins when it's longer, but is still capped.
    """
    ceiling = min(policy.max_delay, policy.base_delay * 2 ** (attempt - 1))
    delay = rand() * ceiling
    if retry_after is not None:
        delay = max(delay, min(retry_after, policy.max_delay))
    return delay


def stream_with_retries[T](
    open_stream: Callable[[], Iterator[T]],
    policy: RetryPolicy,
    sleep: Callable[[float], None] = time.sleep,
) -> Iterator[T]:
    """Yield from `open_stream()`, retrying retryable failures.

    The key rule: retry only if nothing has been yielded yet. Once the caller has
    received an event (and may already have shown text to the user), starting the
    response over would duplicate it. A mid-stream failure is raised instead.
    """
    for attempt in range(1, policy.max_attempts + 1):
        yielded_any = False
        try:
            for event in open_stream():
                yielded_any = True
                yield event
            return
        except Exception as exc:
            if yielded_any or not is_retryable(exc) or attempt == policy.max_attempts:
                raise
            delay = compute_delay(attempt, policy, retry_after_seconds(exc))
            log.warning(
                "llm_retry",
                extra={
                    "attempt": attempt,
                    "error": type(exc).__name__,
                    "status_code": getattr(exc, "status_code", None),
                    "delay_s": round(delay, 3),
                },
            )
            sleep(delay)
