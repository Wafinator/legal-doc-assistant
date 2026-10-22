"""The agent loop: ask the model, run the tools it asks for, repeat.

One "step" is one model call. Each step ends in one of two ways:
  - stop_reason == "tool_use": run every requested tool, send all the results
    back in a single user message, and take another step
  - anything else: the model is done (or was cut off), so stop

The step limit is the safety net. A model that keeps calling tools without
ever answering would otherwise cost money forever.
"""

import logging
import time
from collections.abc import Iterator
from typing import Any

from sqlalchemy.orm import Session

from app.agent.events import AgentEvent, Done, StopReason, Token, ToolCall, ToolResultEvent
from app.agent.tools import TOOLS, ToolResult, execute_tool
from app.llm.client import LLMClient, LLMResponse, TextDelta, Usage

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """\
You answer questions about legal documents (contracts and court filings) stored in a database.

Use the tools to find the relevant text before answering:
- search_documents finds which documents mention a topic.
- get_section returns the full text of a section by its heading.

Base your answer only on text the tools returned. Cite the document title and \
section heading for each point you make. If the documents don't answer the \
question, say so plainly rather than guessing. You are not giving legal advice; \
you are explaining what the documents say."""


def build_system_prompt(document_id: int | None) -> str:
    if document_id is None:
        return SYSTEM_PROMPT
    return (
        f"{SYSTEM_PROMPT}\n\nThe user is asking about document_id={document_id}. "
        "Pass it to the tools unless the question is clearly about other documents."
    )


def run_agent(
    question: str,
    llm: LLMClient,
    db: Session,
    *,
    document_id: int | None = None,
    max_steps: int = 6,
) -> Iterator[AgentEvent]:
    started = time.perf_counter()
    system = build_system_prompt(document_id)
    messages: list[dict[str, Any]] = [{"role": "user", "content": question}]
    input_tokens = output_tokens = 0

    def done(stop_reason: StopReason, steps: int) -> Done:
        event = Done(
            stop_reason=stop_reason,
            steps=steps,
            usage=Usage(input_tokens, output_tokens),
            latency_ms=round((time.perf_counter() - started) * 1000),
        )
        log.info(
            "agent_done",
            extra={
                "stop_reason": stop_reason,
                "steps": steps,
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "latency_ms": event.latency_ms,
            },
        )
        return event

    for step in range(1, max_steps + 1):
        response: LLMResponse | None = None
        for event in llm.stream_turn(system=system, messages=messages, tools=TOOLS):
            if isinstance(event, TextDelta):
                yield Token(event.text)
            else:
                response = event
        if response is None:
            raise RuntimeError("LLM stream ended without a final response")

        input_tokens += response.usage.input_tokens
        output_tokens += response.usage.output_tokens
        # The assistant turn goes back exactly as received, thinking blocks included.
        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason != "tool_use":
            yield done(_stop_reason(response.stop_reason), step)
            return

        tool_results = []
        for block in response.content:
            if block["type"] != "tool_use":
                continue
            yield ToolCall(id=block["id"], name=block["name"], input=block["input"])
            result = _run_tool(block["name"], block["input"], db)
            yield ToolResultEvent(
                id=block["id"], name=block["name"], is_error=result.is_error, content=result.content
            )
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": block["id"],  # must match the tool_use block's id
                    "content": result.content,
                    "is_error": result.is_error,
                }
            )
        # All results go in ONE user message, even when the model called several tools.
        messages.append({"role": "user", "content": tool_results})

    yield done("max_steps", max_steps)


def _run_tool(name: str, tool_input: dict[str, Any], db: Session) -> ToolResult:
    """Run a tool and log it. A crash inside a tool (a bug, a dropped DB connection)
    becomes an error result, so the model can carry on and the user still gets
    an answer."""
    started = time.perf_counter()
    try:
        result = execute_tool(name, tool_input, db)
    except Exception:
        db.rollback()  # a failed query leaves the session unusable until rolled back
        log.exception("tool_crashed", extra={"tool": name})
        result = ToolResult('{"error": "The tool failed unexpectedly."}', is_error=True)
    log.info(
        "tool_call",
        extra={
            "tool": name,
            "input": tool_input,
            "is_error": result.is_error,
            "latency_ms": round((time.perf_counter() - started) * 1000),
        },
    )
    return result


def _stop_reason(api_stop_reason: str | None) -> StopReason:
    if api_stop_reason == "max_tokens":
        return "max_tokens"
    if api_stop_reason == "refusal":
        return "refusal"
    return "answered"  # end_turn, stop_sequence
