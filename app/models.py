"""ORM models."""

from datetime import datetime

from sqlalchemy import Computed, DateTime, Index, Text, func
from sqlalchemy.dialects.postgresql import TSVECTOR
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # A generated column: Postgres computes it from title + content on every
    # insert/update, so it can never drift out of sync with the text. The title
    # gets weight 'A' so a match in the title ranks above a match in the body.
    search_vector: Mapped[str] = mapped_column(
        TSVECTOR,
        Computed(
            "setweight(to_tsvector('english', title), 'A') || "
            "setweight(to_tsvector('english', content), 'B')",
            persisted=True,
        ),
        deferred=True,  # never loaded unless asked for; it's only used in WHERE clauses
    )

    __table_args__ = (
        # GIN is the index type for "which rows contain this word" lookups.
        Index("ix_documents_search_vector", "search_vector", postgresql_using="gin"),
    )

    @property
    def char_count(self) -> int:
        return len(self.content)
