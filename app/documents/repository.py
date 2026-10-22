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


# ts_headline options: up to 2 fragments of about 10-30 words around the matches,
# with matched words wrapped in ** so the model can see why a document matched.
_HEADLINE_OPTIONS = "MaxFragments=2, MinWords=10, MaxWords=30, StartSel=**, StopSel=**"


def search_documents(
    db: Session, query: str, document_id: int | None = None, limit: int = 5
) -> list[Row]:
    """Full-text search ranked by relevance.

    websearch_to_tsquery parses the query like a search engine does: plain words
    are ANDed, "quoted phrases" must appear together, `or` is OR, and -word
    excludes. It never raises on odd user input, unlike to_tsquery. Words are
    stemmed, so "terminating" also matches "terminate" and "termination".
    """
    tsquery = func.websearch_to_tsquery("english", query)
    rank = func.ts_rank(Document.search_vector, tsquery)
    stmt = (
        select(
            Document.id.label("document_id"),
            Document.title,
            func.ts_headline("english", Document.content, tsquery, _HEADLINE_OPTIONS).label(
                "snippet"
            ),
            rank.label("rank"),
        )
        .where(Document.search_vector.op("@@")(tsquery))
        .order_by(rank.desc(), Document.id)
        .limit(limit)
    )
    if document_id is not None:
        stmt = stmt.where(Document.id == document_id)
    return list(db.execute(stmt).all())
