"""Unit tests for the GitHub OAuth helper."""
from __future__ import annotations

import httpx
import pytest

from streamload.auth.github import GithubProfile, fetch_github_profile


@pytest.mark.asyncio
async def test_fetch_github_profile_returns_user_with_primary_email():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={
                "id": 12345, "login": "alfanowski", "name": "Andrea Alfano",
                "email": None, "avatar_url": "https://gh/x.png",
            })
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=[
                {"email": "secondary@example.com", "primary": False, "verified": True},
                {"email": "andrea@example.com", "primary": True, "verified": True},
            ])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as gh:
        prof = await fetch_github_profile(token="ghu_xyz", http=gh)
    assert prof == GithubProfile(
        id=12345, login="alfanowski", email="andrea@example.com",
        name="Andrea Alfano", avatar_url="https://gh/x.png",
    )


@pytest.mark.asyncio
async def test_fetch_github_profile_falls_back_to_user_email_when_no_primary():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/user":
            return httpx.Response(200, json={
                "id": 99, "login": "noemail", "name": None,
                "email": "user-set@example.com", "avatar_url": None,
            })
        if request.url.path == "/user/emails":
            return httpx.Response(200, json=[])
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as gh:
        prof = await fetch_github_profile(token="ghu_xyz", http=gh)
    assert prof.email == "user-set@example.com"


@pytest.mark.asyncio
async def test_fetch_github_profile_raises_on_invalid_token():
    transport = httpx.MockTransport(lambda r: httpx.Response(401))
    async with httpx.AsyncClient(transport=transport, base_url="https://api.github.com") as gh:
        with pytest.raises(ValueError, match="invalid github token"):
            await fetch_github_profile(token="bad", http=gh)
