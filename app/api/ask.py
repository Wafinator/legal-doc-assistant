"""POST /ask: run the agent and stream its progress and answer as Server-Sent Events."""

import logging
import time
from collections.abc import Iterator
from typing import Annotated

import anthropic
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, StringConstraints

from app.agent.loop import run_agent
from app.api.documents import DbSession
from app.api.sse import agent_event_to_sse, format_sse
from app.config import get_settings
from app.db import SessionLocal
from app.documents import repository
from app.llm.client import LLMClient, get_llm_client

log = logging.getLogger(__name__)

router = APIRouter(tags=["ask"])

MAX_QUESTION_CHARS = 2000


class AskRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_QUESTION_CHARS)
    ]
    document_id: int | None = None


@router.post(
    "/ask",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}}},
)
def ask(
    body: AskRequest,
    db: DbSession,
    llm: Annotated[LLMClient, Depends(get_llm_client)],
) -> StreamingResponse:
    # Everything that can fail with a proper status code has to happen here,
    # before the stream starts. Once the first byte is sent the status is 200,
    # and any later failure can only be reported as an `error` event.
    if body.document_id is not None and repository.get_document(db, body.document_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    return StreamingResponse(
        _stream(body.question, body.document_id, llm),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # tell proxies like nginx not to buffer the stream
        },
    )


def _stream(question: str, document_id: int | None, llm: LLMClient) -> Iterator[str]:
    """Runs after ask() has returned, while the response body is being sent.

    It opens its own DB session instead of using the request's: this generator
    outlives the endpoint function, so a session tied to the request could be
    closed before the stream finishes.
    """
    settings = get_settings()
    deadline = time.monotonic() + settings.agent_timeout_s
    db = SessionLocal()
    events = run_agent(
        question, llm, db, document_id=document_id, max_steps=settings.agent_max_steps
    )
    try:
        for event in events:
            yield agent_event_to_sse(event)
            # Checked between events: a single model call is already bounded by
            # the LLM read timeout, so this caps the run as a whole.
            if time.monotonic() > deadline:
                log.warning("agent_timeout", extra={"timeout_s": settings.agent_timeout_s})
                yield _error("timeout", "The answer took too long and was stopped.")
                return
    except (anthropic.APIStatusError, anthropic.APIConnectionError) as exc:
        log.error("agent_failed", extra={"error": type(exc).__name__})
        yield _error("llm_unavailable", "The language model is unavailable. Please try again.")
    except Exception:
        # Full details go to the log; the client gets a generic message, never a stack trace.
        log.exception("agent_failed")
        yield _error("internal_error", "Something went wrong while answering.")
    finally:
        events.close()  # stops the agent (and any open LLM stream) if we left early
        db.close()


def _error(code: str, message: str) -> str:
    return format_sse("error", {"code": code, "message": message})
