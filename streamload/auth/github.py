"""Helpers around the GitHub OAuth-issued access token."""
from __future__ import annotations

from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class GithubProfile:
    id: int
    login: str
    email: str
    name: str | None
    avatar_url: str | None


async def fetch_github_profile(*, token: str, http: httpx.AsyncClient) -> GithubProfile:
    """Calls GET /user and GET /user/emails to assemble a complete profile.

    Raises:
        ValueError: if the token is invalid (any 401/403 from GitHub) or no
            usable email address can be determined.
    """
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    user_resp = await http.get("/user", headers=headers)
    if user_resp.status_code in (401, 403):
        raise ValueError("invalid github token")
    user_resp.raise_for_status()
    user = user_resp.json()

    # Prefer the primary verified email from /user/emails (more authoritative).
    emails_resp = await http.get("/user/emails", headers=headers)
    primary_email: str | None = None
    if emails_resp.status_code == 200:
        for entry in emails_resp.json():
            if entry.get("primary") and entry.get("verified"):
                primary_email = entry.get("email")
                break

    email = primary_email or user.get("email")
    if not email:
        raise ValueError("no email available for github user")

    return GithubProfile(
        id=int(user["id"]),
        login=str(user["login"]),
        email=str(email),
        name=user.get("name"),
        avatar_url=user.get("avatar_url"),
    )
