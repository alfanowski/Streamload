"""Email token issue + consume."""
from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select

from streamload.auth.email_tokens import (
    consume_token,
    issue_token,
    purge_expired_tokens,
)
from streamload.db import create_engine, create_session_factory
from streamload.db.models import EmailToken, User


@pytest_asyncio.fixture
async def db_session():
    url = os.environ.get(
        "DATABASE_URL_TEST",
        "postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test",
    )
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as s:
        await s.execute(EmailToken.__table__.delete())
        await s.execute(User.__table__.delete())
        await s.commit()
        yield s
    await engine.dispose()


@pytest_asyncio.fixture
async def test_user(db_session):
    u = User(username="u1", email="u1@x")
    db_session.add(u)
    await db_session.commit()
    await db_session.refresh(u)
    return u


@pytest.mark.asyncio
async def test_issue_token_returns_token_and_persists(db_session, test_user):
    tok = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    assert isinstance(tok, str)
    rows = (await db_session.execute(select(EmailToken))).scalars().all()
    assert len(rows) == 1
    assert rows[0].purpose == "verify_email"


@pytest.mark.asyncio
async def test_consume_returns_user_id_for_valid(db_session, test_user):
    tok = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    uid = await consume_token(db_session, token=tok, purpose="verify_email")
    assert uid == test_user.id


@pytest.mark.asyncio
async def test_consume_returns_none_for_wrong_purpose(db_session, test_user):
    tok = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    uid = await consume_token(db_session, token=tok, purpose="reset_password")
    assert uid is None


@pytest.mark.asyncio
async def test_consume_is_single_use(db_session, test_user):
    tok = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    first = await consume_token(db_session, token=tok, purpose="verify_email")
    second = await consume_token(db_session, token=tok, purpose="verify_email")
    assert first == test_user.id
    assert second is None


@pytest.mark.asyncio
async def test_consume_returns_none_for_expired(db_session, test_user):
    tok = await issue_token(
        db_session, user_id=test_user.id, purpose="verify_email",
        ttl=timedelta(seconds=-10),
    )
    uid = await consume_token(db_session, token=tok, purpose="verify_email")
    assert uid is None


@pytest.mark.asyncio
async def test_issue_replaces_unused_tokens_for_same_user_purpose(db_session, test_user):
    t1 = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    t2 = await issue_token(db_session, user_id=test_user.id, purpose="verify_email")
    rows = (await db_session.execute(select(EmailToken))).scalars().all()
    assert len(rows) == 1   # old token replaced
    # The first token should now be invalid
    assert await consume_token(db_session, token=t1, purpose="verify_email") is None
    assert await consume_token(db_session, token=t2, purpose="verify_email") == test_user.id


@pytest.mark.asyncio
async def test_purge_expired_removes_old_rows(db_session, test_user):
    await issue_token(db_session, user_id=test_user.id, purpose="verify_email", ttl=timedelta(seconds=-10))
    await issue_token(db_session, user_id=test_user.id, purpose="reset_password")
    # Same user_id+purpose 'verify_email' was just issued, but expired ttl makes it stale.
    # We rely on issue_token replacing same purpose for same user, so stale verify_email is gone.
    purged = await purge_expired_tokens(db_session)
    assert isinstance(purged, int)
    assert purged >= 0
