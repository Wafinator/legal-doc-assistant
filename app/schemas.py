"""Pydantic models for request and response bodies.

These are the API contract, kept separate from the ORM model on purpose: the
database shape can change without silently changing what clients see, and
internal columns like `search_vector` can never leak into a response.
"""

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, StringConstraints

MAX_TITLE_CHARS = 200
MAX_DOCUMENT_CHARS = 500_000  # roughly a 150-page filing

# strip_whitespace runs before the length check, so "   " becomes "" and fails min_length=1.
Title = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_TITLE_CHARS)
]
Content = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_DOCUMENT_CHARS)
]


class DocumentCreate(BaseModel):
    # extra="forbid" rejects unknown fields with a 422 instead of silently
    # ignoring a typo like "contnet".
    model_config = ConfigDict(extra="forbid")

    title: Title
    content: Content


class DocumentSummary(BaseModel):
    """List view: everything except the (potentially huge) content."""

    # from_attributes lets Pydantic read fields off an ORM object (doc.title),
    # not only off dicts.
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    created_at: datetime
    char_count: int


class DocumentRead(DocumentSummary):
    content: str


class DocumentList(BaseModel):
    items: list[DocumentSummary]
    total: int
    limit: int
    offset: int
