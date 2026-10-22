"""The two tools the model can call, and the code that runs them.

Each tool has two halves:
  - a JSON schema in TOOLS, which tells the model the tool exists and what to send
  - a Pydantic input model + handler, which validate what the model actually
    sent and run it

The model usually sends valid input, but "usually" isn't enough, so every
input is validated. Bad input becomes an error result the model can read
and correct, never an exception that breaks the request.
"""

import json
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy.orm import Session

from app.documents import repository
from app.documents.sections import find_section, split_sections

MAX_SECTION_CHARS = 20_000

TOOLS: list[dict[str, Any]] = [
    {
        "name": "search_documents",
        "description": (
            "Keyword search over the stored legal documents. Returns up to 5 matches, "
            "best first, each with a snippet where matched words are wrapped in **. "
            "Use it to find which document, and roughly where, a topic is covered. "
            "Supports quoted phrases and -word to exclude a word."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Keywords, e.g. termination notice"},
                "document_id": {
                    "type": "integer",
                    "description": "Only search this document. Omit to search all documents.",
                },
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_section",
        "description": (
            "Return the full text of one section of a document, looked up by its heading "
            "(case-insensitive; a partial heading like 'termination' also works). If no "
            "heading matches, the error lists the headings the document has."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "document_id": {"type": "integer"},
                "heading": {"type": "string", "description": "e.g. '8. TERMINATION'"},
            },
            "required": ["document_id", "heading"],
            "additionalProperties": False,
        },
    },
]


class SearchInput(BaseModel):
    query: str = Field(min_length=1, max_length=500)
    document_id: int | None = None


class GetSectionInput(BaseModel):
    document_id: int
    heading: str = Field(min_length=1, max_length=200)


@dataclass(frozen=True)
class ToolResult:
    content: str  # JSON text: what the model reads
    is_error: bool = False


def execute_tool(name: str, tool_input: dict[str, Any], db: Session) -> ToolResult:
    """Run one tool call. Expected problems (unknown tool, bad input, missing
    document) come back as error results; unexpected exceptions are left to
    the caller."""
    handler = _HANDLERS.get(name)
    if handler is None:
        return _error(f"Unknown tool {name!r}. Available tools: {', '.join(_HANDLERS)}.")
    try:
        return handler(tool_input, db)
    except ValidationError as exc:
        # include_url=False keeps pydantic's docs links out of what the model reads.
        return _error(f"Invalid input for {name}: {exc.errors(include_url=False)}")


def _search_documents(tool_input: dict[str, Any], db: Session) -> ToolResult:
    args = SearchInput.model_validate(tool_input)
    rows = repository.search_documents(db, args.query, document_id=args.document_id)
    results = [
        {
            "document_id": row.document_id,
            "title": row.title,
            "snippet": row.snippet,
            "rank": round(row.rank, 4),
        }
        for row in rows
    ]
    return _ok({"query": args.query, "results": results})


def _get_section(tool_input: dict[str, Any], db: Session) -> ToolResult:
    args = GetSectionInput.model_validate(tool_input)
    doc = repository.get_document(db, args.document_id)
    if doc is None:
        return _error(f"Document {args.document_id} not found.")
    sections = split_sections(doc.content)
    section = find_section(sections, args.heading)
    if section is None:
        return _error(
            f"No heading matching {args.heading!r} in document {doc.id}.",
            available_headings=[s.heading for s in sections],
        )
    text = section.text
    truncated = len(text) > MAX_SECTION_CHARS
    return _ok(
        {
            "document_id": doc.id,
            "title": doc.title,
            "heading": section.heading,
            "text": text[:MAX_SECTION_CHARS],
            "truncated": truncated,  # said out loud, so the model knows it didn't see it all
        }
    )


_HANDLERS = {
    "search_documents": _search_documents,
    "get_section": _get_section,
}


def _ok(payload: dict[str, Any]) -> ToolResult:
    return ToolResult(json.dumps(payload))


def _error(message: str, **details: Any) -> ToolResult:
    return ToolResult(json.dumps({"error": message, **details}), is_error=True)
