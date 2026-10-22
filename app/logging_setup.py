"""Structured (JSON) logging.

Every log line is one JSON object, so a log tool can filter on fields
(`event == "llm_call" and latency_ms > 2000`) instead of grepping text.

Usage anywhere in the app:

    log = logging.getLogger(__name__)
    log.info("llm_call", extra={"model": "...", "latency_ms": 812})

The message is the event name; everything in `extra` becomes a JSON field.
"""

import json
import logging
from contextvars import ContextVar
from datetime import UTC, datetime

# A ContextVar is like AsyncLocal<T> in C#: each request sees its own value,
# even when many requests are handled at once. Phase 4's middleware sets it.
request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)

# Attributes every LogRecord has. Anything else on the record came from `extra`.
_STANDARD_ATTRS = set(vars(logging.makeLogRecord({}))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
        }
        if (request_id := request_id_var.get()) is not None:
            payload["request_id"] = request_id
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS:
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        # default=str keeps logging from crashing on values json can't encode.
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO") -> None:
    """Install the JSON handler on the root logger. Safe to call more than once.

    Only our own handler is swapped out; any others are left alone. pytest's
    `caplog` fixture works by adding a handler to the root logger, and wiping
    the list would silently break log assertions in tests.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())
    root = logging.getLogger()
    root.handlers = [h for h in root.handlers if not isinstance(h.formatter, JsonFormatter)]
    root.addHandler(handler)
    root.setLevel(level)
    # The SDK's HTTP library logs every request at INFO; our llm_call line already covers it.
    logging.getLogger("httpx2").setLevel(logging.WARNING)
