"""Server-Sent Events: the wire format and the mapping from agent events to it.

SSE is plain text over a long-lived HTTP response. Each message is a few
`field: value` lines followed by a blank line:

    event: token
    data: {"text": "Either party may"}

The browser's EventSource API (or `curl -N`) reads these as they arrive. It's
one-way, server to client, which is all a streamed answer needs, so it's
simpler than WebSockets.
"""

import json
from typing import Any

from app.agent.events import AgentEvent, Done, Token, ToolCall, ToolResultEvent

TOOL_RESULT_PREVIEW_CHARS = 300


def format_sse(event: str, data: dict[str, Any]) -> str:
    # json.dumps never emits a raw newline (they're escaped as \n), so the
    # payload always fits on one `data:` line and can't break the framing.
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def agent_event_to_sse(event: AgentEvent) -> str:
    match event:
        case Token(text=text):
            return format_sse("token", {"text": text})
        case ToolCall(id=id_, name=name, input=tool_input):
            return format_sse("tool_call", {"id": id_, "name": name, "input": tool_input})
        case ToolResultEvent(id=id_, name=name, is_error=is_error, content=content):
            # A preview only: the client needs to show progress, not a 20,000-char section.
            return format_sse(
                "tool_result",
                {
                    "id": id_,
                    "name": name,
                    "is_error": is_error,
                    "preview": content[:TOOL_RESULT_PREVIEW_CHARS],
                },
            )
        case Done():
            return format_sse(
                "done",
                {
                    "stop_reason": event.stop_reason,
                    "steps": event.steps,
                    "usage": {
                        "input_tokens": event.usage.input_tokens,
                        "output_tokens": event.usage.output_tokens,
                    },
                    "latency_ms": event.latency_ms,
                },
            )
    raise TypeError(f"Unhandled agent event: {event!r}")
