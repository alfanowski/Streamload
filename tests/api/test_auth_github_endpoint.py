"""End-to-end tests for POST /api/auth/github."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.db import get_session as gs
from streamload.db.models import User


@pytest.mark.asyncio
async def test_github_login_creates_new_user_with_profile_incomplete(
    api_client: httpx.AsyncClient, monkeypatch
) -> None:
    """First-time GitHub login → new user row, profile_complete=false, session issued."""

    async def fake_fetch(*, token, http):
        from streamload.auth.github import GithubProfile
        return GithubProfile(
            id=12345, login="newuser", email="new@example.com",
            name="New User", avatar_url=None,
        )

    monkeypatch.setattr(
        "streamload.api.routes.auth_github.fetch_github_profile", fake_fetch,
    )

    r = await api_client.post("/api/auth/github", json={"access_token": "ghu_x"})
    assert r.status_code == 200
    body = r.json()
    assert body["github_username"] == "newuser"
    assert body["email"] == "new@example.com"
    assert body["profile_complete"] is False

    # Session cookie set.
    assert "session" in r.cookies

    async for db in gs():
        u = (await db.execute(
            select(User).where(User.github_id == 12345)
        )).scalar_one()
        assert u.username == "newuser"
        assert u.email == "new@example.com"
        break


@pytest.mark.asyncio
async def test_github_login_returns_existing_user(
    api_client: httpx.AsyncClient, monkeypatch
) -> None:
    """Second login with the same github_id → reuses the same user."""

    async def fake_fetch(*, token, http):
        from streamload.auth.github import GithubProfile
        return GithubProfile(
            id=42, login="returning", email="ret@example.com",
            name=None, avatar_url=None,
        )

    monkeypatch.setattr(
        "streamload.api.routes.auth_github.fetch_github_profile", fake_fetch,
    )

    r1 = await api_client.post("/api/auth/github", json={"access_token": "t1"})
    assert r1.status_code == 200
    r2 = await api_client.post("/api/auth/github", json={"access_token": "t2"})
    assert r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_github_login_invalid_token_returns_401(
    api_client: httpx.AsyncClient, monkeypatch
) -> None:
    async def fake_fetch(*, token, http):
        raise ValueError("invalid github token")

    monkeypatch.setattr(
        "streamload.api.routes.auth_github.fetch_github_profile", fake_fetch,
    )

    r = await api_client.post("/api/auth/github", json={"access_token": "bad"})
    assert r.status_code == 401
