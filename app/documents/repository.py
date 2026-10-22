"""Data access for documents.

Routers call these functions instead of building queries themselves, so SQL
lives in one place. In phase 3 the agent's search tool will reuse this module.
"""

from sqlalchemy import func, select
from sqlalchemy.engine import Row
from sqlalchemy.orm import Session

from app.models import Document


def create_document(db: Session, title: str, content: str) -> Document:
    doc = Document(title=title, content=content)
    db.add(doc)
    db.commit()
    db.refresh(doc)  # load server-generated values (id, created_at)
    return doc


def get_document(db: Session, document_id: int) -> Document | None:
    return db.get(Document, document_id)


def list_documents(db: Session, limit: int, offset: int) -> tuple[list[Row], int]:
    """Return one page of document summaries plus the total count.

    Postgres computes the length with char_length() so the full content of
    every document is never sent over the wire just to count it.
    """
    rows = db.execute(
        select(
            Document.id,
            Document.title,
            Document.created_at,
            func.char_length(Document.content).label("char_count"),
        )
        # id breaks ties so paging is stable when two rows share a created_at.
        .order_by(Document.created_at.desc(), Document.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    total = db.scalar(select(func.count()).select_from(Document)) or 0
    return list(rows), total
