"""Parse a Server-Sent Events body back into (event, data) pairs for assertions."""

import json
from typing import Any


def parse_sse(body: str) -> list[tuple[str, dict[str, Any]]]:
    """parse_sse(response.text) -> [("tool_call", {...}), ("token", {...}), ("done", {...})]"""
    events = []
    for frame in body.split("\n\n"):
        if not frame.strip():
            continue
        fields = dict(line.split(": ", 1) for line in frame.splitlines())
        events.append((fields["event"], json.loads(fields["data"])))
    return events
