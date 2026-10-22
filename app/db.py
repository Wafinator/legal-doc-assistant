"""Database engine, session factory and the FastAPI session dependency."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    pass


# pool_pre_ping checks a pooled connection is alive before handing it out,
# so a Postgres restart doesn't surface as errors on the next few requests.
engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """One session per request, always closed afterwards.

    FastAPI runs the code before `yield` when the request starts and the `finally`
    block after the response is sent, which works like a C# `using` block.
    Tests swap this dependency out to point at the test database.
    """
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
