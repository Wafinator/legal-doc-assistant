"""A scripted stand-in for the model, so the app can be tried without an API key.

Set LLM_MODE=demo. Nothing is sent to Anthropic and no tokens are used.

Everything except the model's decisions is real: the agent loop, both tools,
Postgres search and SSE streaming. Where a real model would decide what to
do, this follows a fixed script:

  1. search_documents with keywords taken from the question
  2. get_section on the best match, using one of those keywords as the heading
  3. an answer quoting what the tools returned, clearly labeled as demo output

Every answer starts with a [Demo mode] note so it can't be mistaken for a
real model's output.
"""

import json
import re
import time
from collections.abc import Iterator
from typing import Any

from app.llm.client import LLMResponse, StreamEvent, TextDelta, Usage

_STOPWORDS = {
    "about", "agreement", "does", "doesn't", "from", "have", "says", "should",
    "that", "their", "there", "these", "this", "under", "what", "when", "where",
    "which", "with", "would",
}  # fmt: skip
_DOCUMENT_ID = re.compile(r"document_id=(\d+)")
NOTE = "[Demo mode: no AI model was called; this answer is assembled from the tool results.] "


class DemoLLMClient:
    def __init__(self, word_delay_s: float = 0.03) -> None:
        # A short pause between words makes the streaming visible in a terminal.
        self._word_delay_s = word_delay_s

    def stream_turn(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> Iterator[StreamEvent]:
        question = messages[0]["content"]
        keywords = _keywords(question)
        results = _tool_results(messages)

        if not results:
            tool_input: dict[str, Any] = {"query": " or ".join(keywords) or question}
            if match := _DOCUMENT_ID.search(system):
                tool_input["document_id"] = int(match[1])
            yield _tool_call("search_documents", tool_input, step=1)
            return

        search = results[0]
        hits = search.get("results", [])
        if len(results) == 1 and hits and keywords:
            # Crude stemming: "terminated"[:6] = "termin" also matches "TERMINATION".
            heading = max(keywords, key=len)[:6]
            yield _tool_call(
                "get_section", {"document_id": hits[0]["document_id"], "heading": heading}, step=2
            )
            return

        yield from self._answer(_compose_answer(hits, results[1] if len(results) > 1 else None))

    def _answer(self, text: str) -> Iterator[StreamEvent]:
        for word in re.findall(r"\S+\s*", text):
            if self._word_delay_s:
                time.sleep(self._word_delay_s)
            yield TextDelta(word)
        yield LLMResponse(
            content=[{"type": "text", "text": text}], stop_reason="end_turn", usage=Usage(0, 0)
        )


def _keywords(question: str) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z'-]{3,}", question.lower())
    return [w for w in dict.fromkeys(words) if w not in _STOPWORDS]  # dedupe, keep order


def _tool_results(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every tool result so far, oldest first, parsed from its JSON content."""
    return [
        json.loads(block["content"])
        for message in messages
        if message["role"] == "user" and isinstance(message["content"], list)
        for block in message["content"]
        if block["type"] == "tool_result"
    ]


def _tool_call(name: str, tool_input: dict[str, Any], step: int) -> LLMResponse:
    return LLMResponse(
        content=[{"type": "tool_use", "id": f"demo_{step}", "name": name, "input": tool_input}],
        stop_reason="tool_use",
        usage=Usage(0, 0),
    )


def _compose_answer(hits: list[dict[str, Any]], section: dict[str, Any] | None) -> str:
    if not hits:
        return NOTE + "No stored document matched the keywords in your question."
    top = hits[0]
    if section and "error" not in section:
        excerpt = " ".join(section["text"].split())[:400]
        return (
            NOTE + f'The closest match is "{top["title"]}", section "{section["heading"]}": '
            f'"{excerpt}"'
        )
    snippet = " ".join(top["snippet"].split())
    return NOTE + f'The closest match is "{top["title"]}". Relevant passage: "{snippet}"'
