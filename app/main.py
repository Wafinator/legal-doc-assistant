"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import documents
from app.db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: create any missing tables. Fine for one table. A real
    # service would use Alembic migrations instead (see README).
    Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    """Build the app. A factory (rather than only a module-level global) lets
    tests create a fresh app and override its dependencies."""
    app = FastAPI(title="Legal Doc Assistant", version="0.1.0", lifespan=lifespan)
    app.include_router(documents.router)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
