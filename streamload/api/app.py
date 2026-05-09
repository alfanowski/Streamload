"""FastAPI application factory + lifespan."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from streamload.db import init as db_init, shutdown as db_shutdown

from .routes import auth, catalog, collections, email, health, me, passkey, search
from .routes.catalog import admin_router as catalog_admin_router


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Start/stop the DB connection pool around the app lifecycle."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    db_init(url)
    try:
        yield
    finally:
        await db_shutdown()


def create_app() -> FastAPI:
    """Construct the FastAPI app instance."""
    app = FastAPI(
        title="Streamload",
        description="Private streaming platform.",
        version=_get_version(),
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.include_router(auth.router, prefix="/api")
    app.include_router(catalog.router, prefix="/api")
    app.include_router(catalog_admin_router, prefix="/api")
    app.include_router(collections.router, prefix="/api")
    app.include_router(email.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(passkey.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    return app


def _get_version() -> str:
    try:
        from streamload.version import __version__
        return __version__
    except Exception:
        return "0.0.0"


# ASGI app for granian / uvicorn:
# `granian streamload.api.app:app`
app = create_app()
