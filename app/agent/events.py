"""What the agent loop reports as it runs.

run_agent yields these in order. Phase 4 turns each one into an SSE event,
but the loop itself knows nothing about HTTP, so tests can collect them
with a plain list().
"""

from dataclasses import dataclass
from typing import Any, Literal

from app.llm.client import Usage

# answered:   the model gave its final answer
# max_steps:  the step limit ran out while the model was still calling tools
# max_tokens: the answer was cut off by the output token cap
# refusal:    the model declined to answer
StopReason = Literal["answered", "max_steps", "max_tokens", "refusal"]


@dataclass(frozen=True)
class Token:
    """A chunk of text from the model, streamed as it's generated."""

    text: str


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ToolResultEvent:
    id: str
    name: str
    is_error: bool
    content: str


@dataclass(frozen=True)
class Done:
    stop_reason: StopReason
    steps: int  # number of model calls made
    usage: Usage  # summed over every step
    latency_ms: int


AgentEvent = Token | ToolCall | ToolResultEvent | Done
