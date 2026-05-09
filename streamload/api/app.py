"""FastAPI application factory + lifespan."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from streamload.db import init as db_init, shutdown as db_shutdown
from streamload.utils.logger import get_logger

from .routes import admin, auth, catalog, collections, email, episodes, favorites, health, intro, library, me, passkey, progress, search, settings, watchlist

log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize DB, bootstrap admin, start the catalog refresh worker."""
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload",
    )
    db_init(url)

    await _ensure_admin_user()
    refresh_task = asyncio.create_task(_run_catalog_refresh_loop())

    try:
        yield
    finally:
        refresh_task.cancel()
        try:
            await refresh_task
        except (asyncio.CancelledError, Exception):
            pass

        await db_shutdown()


async def _ensure_admin_user() -> None:
    """Provision the admin from STREAMLOAD_ADMIN_* env vars.

    On first boot creates the admin with the env password. On subsequent boots
    ensures the user exists with role=admin and is not disabled, but does NOT
    overwrite the password — the operator can set/rotate it from the app.

    To force a password reset, set STREAMLOAD_ADMIN_RESET_PASSWORD=1 once.
    """
    username = os.environ.get("STREAMLOAD_ADMIN_USERNAME", "").strip()
    email = os.environ.get("STREAMLOAD_ADMIN_EMAIL", "").strip()
    password = os.environ.get("STREAMLOAD_ADMIN_PASSWORD", "")
    force_reset = os.environ.get("STREAMLOAD_ADMIN_RESET_PASSWORD", "") in {"1", "true", "yes"}
    if not (username and email and password):
        log.info("Admin bootstrap skipped: STREAMLOAD_ADMIN_* not fully set")
        return

    from datetime import UTC, datetime
    from sqlalchemy import select
    from streamload.auth.passwords import hash_password
    from streamload.db.models import User
    from streamload.db.session import _session_factory

    async with _session_factory() as db:
        existing = (await db.execute(
            select(User).where(User.username == username)
        )).scalar_one_or_none()
        if existing is None:
            admin = User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                role="admin",
                email_verified_at=datetime.now(UTC),
                email_required=False,
            )
            db.add(admin)
            await db.commit()
            log.info("Bootstrap created admin %r", username)
        else:
            existing.email = email
            existing.role = "admin"
            existing.disabled_at = None
            if existing.email_verified_at is None:
                existing.email_verified_at = datetime.now(UTC)
            if force_reset:
                existing.password_hash = hash_password(password)
                log.info("Bootstrap reset admin password for %r", username)
            await db.commit()
            log.info("Bootstrap ensured admin %r", username)


async def _run_catalog_refresh_loop() -> None:
    """Background task: refresh due collections every 10 minutes.

    On first run after a fresh DB, this populates everything. After that, only
    collections older than their TTL are refreshed.
    """
    import httpx
    from streamload.catalog.tmdb import TmdbClient
    from streamload.catalog.worker import POLL_INTERVAL_SECONDS, refresh_due_collections, _load_services
    from streamload.db.session import _session_factory

    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        log.warning("Catalog refresh disabled: TMDB_API_KEY missing")
        return

    services = _load_services()
    # Stagger first tick so we don't block readiness probes.
    await asyncio.sleep(5)

    while True:
        try:
            async with _session_factory() as db:
                async with httpx.AsyncClient(timeout=20) as http:
                    tmdb = TmdbClient(api_key=api_key, http=http)
                    refreshed = await refresh_due_collections(
                        db, tmdb_client=tmdb, services=services,
                    )
                    if refreshed:
                        log.info("Catalog refreshed: %s", ", ".join(refreshed))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("Catalog refresh tick failed", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)


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
    app.include_router(collections.router, prefix="/api")
    app.include_router(email.router, prefix="/api")
    app.include_router(health.router, prefix="/api")
    app.include_router(me.router, prefix="/api")
    app.include_router(passkey.router, prefix="/api")
    app.include_router(search.router, prefix="/api")
    app.include_router(progress.router, prefix="/api")
    app.include_router(favorites.router, prefix="/api")
    app.include_router(watchlist.router, prefix="/api")
    app.include_router(library.router, prefix="/api")
    app.include_router(intro.router, prefix="/api")
    app.include_router(episodes.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    app.include_router(admin.router, prefix="/api")
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
