"""Shared API test fixtures."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio
from sqlalchemy import text

from streamload.api.app import create_app
from streamload.db import init as db_init, shutdown as db_shutdown
from streamload.db.session import _session_factory  # for cleanup


async def _truncate_all(factory):
    async with factory() as s:
        # Order respects FKs (children first).
        for table in (
            "watch_progress", "favorites", "watchlist",
            "collection_items", "catalog_sources", "tv_episodes",
            "catalog_items", "collections",
            "email_tokens", "webauthn_credentials", "sessions",
            "users",
        ):
            await s.execute(text(f"TRUNCATE TABLE {table} CASCADE"))
        await s.commit()


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    test_url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    db_init(test_url)
    # Truncate before each test for isolation.
    from streamload.db.session import _session_factory as f
    await _truncate_all(f)

    # Reset rate limiters between tests for isolation.
    from streamload.api.routes.auth import _login_limiter_per_ip, _login_limiter_per_user
    _login_limiter_per_ip.reset()
    _login_limiter_per_user.reset()

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await db_shutdown()
