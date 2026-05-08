"""Session creation, lookup, expiry."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from streamload.auth.sessions import (
    DEFAULT_SESSION_TTL,
    create_session,
    delete_session,
    get_session_user_id,
    refresh_session,
)
from streamload.db import create_engine, create_session_factory
from streamload.db.models import Session as SessionModel, User


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        await s.execute(SessionModel.__table__.delete())
        await s.execute(User.__table__.delete())
        await s.commit()
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session):
    u = User(username="alice", email="alice@example.com")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_create_session_returns_token_and_persists(db_session, test_user):
    token = await create_session(db_session, user_id=test_user.id)
    assert isinstance(token, str)
    rows = (await db_session.execute(select(SessionModel))).scalars().all()
    assert len(rows) == 1


@pytest.mark.asyncio
async def test_get_session_user_id_returns_user(db_session, test_user):
    token = await create_session(db_session, user_id=test_user.id)
    user_id = await get_session_user_id(db_session, token=token)
    assert user_id == test_user.id


@pytest.mark.asyncio
async def test_get_session_user_id_returns_none_for_unknown(db_session):
    user_id = await get_session_user_id(db_session, token="bogus")
    assert user_id is None


@pytest.mark.asyncio
async def test_get_session_user_id_returns_none_for_expired(db_session, test_user):
    token = await create_session(db_session, user_id=test_user.id, ttl=timedelta(seconds=-10))
    user_id = await get_session_user_id(db_session, token=token)
    assert user_id is None


@pytest.mark.asyncio
async def test_refresh_session_updates_last_seen_and_extends(db_session, test_user):
    token = await create_session(db_session, user_id=test_user.id, ttl=timedelta(hours=1))
    before = datetime.now(UTC) - timedelta(seconds=1)
    await refresh_session(db_session, token=token)
    s = (await db_session.execute(select(SessionModel))).scalar_one()
    assert s.last_seen_at >= before


@pytest.mark.asyncio
async def test_delete_session_removes_row(db_session, test_user):
    token = await create_session(db_session, user_id=test_user.id)
    await delete_session(db_session, token=token)
    rows = (await db_session.execute(select(SessionModel))).scalars().all()
    assert rows == []
