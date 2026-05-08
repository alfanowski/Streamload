"""Shared API test fixtures."""
from __future__ import annotations

import os
from collections.abc import AsyncIterator

import httpx
import pytest_asyncio

from streamload.api.app import create_app
from streamload.db import init as db_init, shutdown as db_shutdown


@pytest_asyncio.fixture
async def api_client() -> AsyncIterator[httpx.AsyncClient]:
    test_url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    db_init(test_url)
    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await db_shutdown()
