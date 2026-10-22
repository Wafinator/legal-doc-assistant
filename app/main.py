"""FastAPI application factory."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse

from app.api import ask, documents
from app.config import get_settings
from app.db import Base, engine
from app.llm.client import LLMNotConfiguredError
from app.logging_setup import configure_logging
from app.middleware import RequestLoggingMiddleware


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Startup: create any missing tables. Fine for one table. A real
    # service would use Alembic migrations instead (see README).
    Base.metadata.create_all(engine)
    yield


def create_app() -> FastAPI:
    """Build the app. A factory (rather than only a module-level global) lets
    tests create a fresh app and override its dependencies."""
    configure_logging(get_settings().log_level)
    app = FastAPI(title="Legal Doc Assistant", version="0.1.0", lifespan=lifespan)
    app.add_middleware(RequestLoggingMiddleware)
    app.include_router(documents.router)
    app.include_router(ask.router)

    @app.exception_handler(LLMNotConfiguredError)
    def llm_not_configured(request: Request, exc: LLMNotConfiguredError) -> JSONResponse:
        # 503 Service Unavailable: the request is fine, the server isn't set up to answer it.
        return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
