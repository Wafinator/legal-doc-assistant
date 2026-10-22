"""Shared pytest fixtures.

pytest discovers this file automatically. Any test can request a fixture just by
naming it as a parameter (e.g. `def test_x(client, make_document):`). That's
dependency injection for tests, similar to constructor injection in NUnit/xUnit.
"""

import os

# Point the app at the test database BEFORE importing it: app.db creates its
# engine at import time from DATABASE_URL. CI sets TEST_DATABASE_URL; locally
# the default matches docker-compose.yml.
TEST_DATABASE_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql+psycopg://legal:legal@localhost:5433/legal_docs_test"
)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL

from collections.abc import Callable, Iterator  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import create_app  # noqa: E402
from app.models import Document  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _create_schema() -> Iterator[None]:
    """Once per test run: rebuild the schema from the current models.

    drop_all first so a changed model (new column, new index) never runs
    against a stale table left behind by an earlier run.
    """
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    yield
    engine.dispose()


@pytest.fixture(autouse=True)
def _reset_db() -> None:
    """Before every test: empty all tables so tests can't see each other's data.

    TRUNCATE is used rather than wrapping each test in a rolled-back transaction
    because the app commits for real. RESTART IDENTITY resets ids to 1, so
    ids are predictable inside a test.
    """
    tables = ", ".join(t.name for t in Base.metadata.sorted_tables)
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


@pytest.fixture
def db() -> Iterator[Session]:
    """A session for arranging data or asserting on what the API wrote."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def client() -> Iterator[TestClient]:
    """An in-process HTTP client. No server or port is needed: requests go
    straight into the ASGI app. Using it as a context manager runs the app's
    startup/shutdown (lifespan) like a real server would."""
    with TestClient(create_app()) as c:
        yield c


@pytest.fixture
def make_document(db: Session) -> Callable[..., Document]:
    """Factory fixture: call it to insert a document directly into the DB.

    Use it to arrange state for a test without going through the API under test.
    """

    def _make(
        title: str = "Test Agreement", content: str = "1. TERM\nThe term is one year."
    ) -> Document:
        doc = Document(title=title, content=content)
        db.add(doc)
        db.commit()
        db.refresh(doc)
        return doc

    return _make
