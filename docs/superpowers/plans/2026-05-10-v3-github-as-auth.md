# v3 GitHub as Sole Auth + Profile Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace username/password auth entirely with GitHub OAuth as the sole identity. New users land on the GitHub login screen, authorize, then complete a 4-field profile (Nome, Cognome, Data di nascita, Genere) before reaching `/home`. Returning users skip the profile screen. The `/login` and `/register` pages are deleted.

**Architecture:** The OAuth Device Flow plan (committed earlier today) already saves a GitHub access token after authorization. This plan extends that with: (a) a backend `POST /api/auth/github` endpoint that takes the access token, calls GitHub's `/user` + `/user/emails`, finds-or-creates the user record by `github_id`, and issues a session cookie; (b) a Dart `AuthApi.loginWithGithub(accessToken)` replacing the old `login`/`register` methods; (c) a new `ProfileCompletionPage` shown when `profile_complete = false`; (d) router redirects updated to gate `/home` on both token presence AND profile completion. The OAuth scope expands from `repo` to `repo user:email` so we get the user's primary email.

**Tech Stack:** Backend: FastAPI + SQLAlchemy + Alembic. Client: Flutter 3.41+, Dart 3.11+, riverpod 2.6, freezed 2.5, dio, go_router 14, intl 0.19 (for date formatting).

---

## Source spec

Refines two earlier plans:
- **Plan #4 / sub-plan 6a backend (`docs/superpowers/plans/2026-05-09-v3-backend-reduction.md`)** — kept username/password auth in `/api/auth/register` + `/api/auth/login`. This plan adds `/api/auth/github` and leaves the old endpoints as-is for dev/admin fallback (they're not surfaced in the client UI anymore).
- **OAuth Device Flow plan (`docs/superpowers/plans/2026-05-10-v3-github-oauth-device-flow.md`)** — saved the GitHub token to SecureStorage and used it ONLY to fetch the plugin registry. This plan also uses it to create/restore a backend session.

The terminal state of this plan is: a brand-new user opens the app → first screen is "Accedi con GitHub" → device flow completes → they fill out Nome/Cognome/Data di nascita/Genere → `/home`. A returning user skips the profile screen and goes straight to `/home`. The `/login` and `/register` routes do not exist.

## Operator pre-step

Before running the migration:

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload
source venv/bin/activate
python scripts/reset_users.py  # truncates users + sessions cascade — dev only
```

This wipes the 3 seed users (`alfanowski`, `admin`, `prova`). The operator (and the 10 invited friends) will register fresh via GitHub.

## File structure

### New files

| Path | Created in | Purpose |
|---|---|---|
| `migrations/versions/000X_github_auth.py` | T1 | Alembic migration adding github_id (unique), github_username, first_name, last_name, birth_date, gender, profile_complete |
| `streamload/auth/github.py` | T3 | calls GitHub /user + /user/emails, parses response |
| `streamload/api/routes/auth_github.py` | T3 | POST /api/auth/github endpoint |
| `scripts/reset_users.py` | T0 | dev-only script: truncates users + sessions cascade |
| `tests/auth/test_github_oauth.py` | T3 | mocked httpx exchanges + find-or-create logic |
| `tests/api/test_auth_github_endpoint.py` | T3 | end-to-end with fake GitHub responses via httpx_mock |
| `tests/api/test_me_profile.py` | T4 | PATCH /api/me/profile flow |
| `lib/presentation/pages/profile_completion_page.dart` | T11 | 4-field form for Nome/Cognome/Data/Genere |
| `test/pages/profile_completion_page_test.dart` | T11 | submit + validation tests |

### Modified files (backend)

| Path | Modified in | Change |
|---|---|---|
| `streamload/db/models.py` | T2 | User: add github_id (unique nullable), github_username, first_name, last_name, birth_date, gender, profile_complete; password_hash → nullable |
| `streamload/api/routes/auth.py` | T2 | UserPublic adds first_name, last_name, birth_date, gender, profile_complete |
| `streamload/api/routes/me.py` | T4 | new PATCH /api/me/profile endpoint |
| `streamload/api/app.py` | T3 | mount auth_github router |

### Modified files (client)

| Path | Modified in | Change |
|---|---|---|
| `lib/domain/models/user.dart` | T6 | add firstName, lastName, birthDate, gender, profileComplete |
| `lib/data/remote/endpoints/auth_api.dart` | T7 | drop login/register, add loginWithGithub, add updateProfile |
| `lib/state/auth_provider.dart` | T8 | drop login/register state machine, add loginWithGithub + updateProfile |
| `lib/plugins/github_oauth.dart` | T13 | bump default scope from `repo` to `repo user:email` |
| `lib/presentation/pages/plugin_onboarding_page.dart` | T10 | after device flow + token save, also call backend `loginWithGithub`; route based on profile_complete |
| `lib/router.dart` | T12 | drop /login + /register routes; redirect: no token → /onboarding/github, token + profile incomplete → /onboarding/profile, token + complete → /home |

### Deleted files (client)

| Path | In | Reason |
|---|---|---|
| `lib/presentation/pages/login_page.dart` | T9 | GitHub is now sole auth |
| `lib/presentation/pages/register_page.dart` | T9 | same |
| `test/pages/login_page_test.dart` | T9 | dead code |
| `test/pages/register_page_test.dart` | T9 | dead code |

---

## Phase A — Backend

### Task 0: `scripts/reset_users.py` (operator pre-step helper)

**Files:**
- Create: `scripts/reset_users.py`

- [ ] **Step 1: Write the script**

```python
# scripts/reset_users.py
"""DEV-ONLY: wipe users + sessions cascade so the new GitHub-auth flow can
register everyone fresh. Refuses to run if STREAMLOAD_ENV=production."""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import text  # noqa: E402

from streamload.db import init as db_init, shutdown as db_shutdown  # noqa: E402
from streamload.db.session import _session_factory  # noqa: E402


async def main() -> None:
    if os.environ.get("STREAMLOAD_ENV") == "production":
        print("refusing to truncate users in production")
        sys.exit(1)
    await db_init()
    try:
        async with _session_factory() as db:
            # CASCADE drops sessions, webauthn_credentials, watch_progress,
            # favorites, watchlist, etc.
            await db.execute(text("TRUNCATE users CASCADE"))
            await db.commit()
        print("users truncated (CASCADE)")
    finally:
        await db_shutdown()


if __name__ == "__main__":
    asyncio.run(main())
```

- [ ] **Step 2: Sanity check the script imports cleanly**

```bash
venv/bin/python -c "import scripts.reset_users"
```

- [ ] **Step 3: Commit**

```bash
git add scripts/reset_users.py
git commit -m "scripts: dev-only reset_users.py — truncates users + sessions cascade"
```

---

### Task 1: Alembic migration — add GitHub auth + profile fields

**Files:**
- Create: `migrations/versions/<auto>_github_auth.py` (use `alembic revision --autogenerate` or hand-write)
- The User model changes in T2 will drive the migration

- [ ] **Step 1: Write the migration BY HAND** (autogenerate after T2 also works; either is fine — pick one. By hand is reliable.)

```python
"""github auth + profile fields

Revision ID: 0009_github_auth
Revises: 0008_v3_reduction  # whatever the previous head is — check `alembic heads`
Create Date: 2026-05-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_github_auth"
down_revision = "0008_v3_reduction"
branch_labels = None
depends_on = None

GENDER_ENUM = sa.Enum(
    "male", "female", "non_binary", "prefer_not_to_say",
    name="gender",
)


def upgrade() -> None:
    GENDER_ENUM.create(op.get_bind(), checkfirst=True)
    op.add_column("users",
        sa.Column("github_id", sa.BigInteger(), nullable=True))
    op.add_column("users",
        sa.Column("github_username", sa.String(length=64), nullable=True))
    op.add_column("users",
        sa.Column("first_name", sa.String(length=64), nullable=True))
    op.add_column("users",
        sa.Column("last_name", sa.String(length=64), nullable=True))
    op.add_column("users",
        sa.Column("birth_date", sa.Date(), nullable=True))
    op.add_column("users",
        sa.Column("gender", GENDER_ENUM, nullable=True))
    op.add_column("users",
        sa.Column("profile_complete", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_unique_constraint("uq_users_github_id", "users", ["github_id"])
    # password_hash becomes nullable so GitHub-only users have no password.
    op.alter_column("users", "password_hash",
                    existing_type=sa.String(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash",
                    existing_type=sa.String(),
                    nullable=False)
    op.drop_constraint("uq_users_github_id", "users", type_="unique")
    op.drop_column("users", "profile_complete")
    op.drop_column("users", "gender")
    op.drop_column("users", "birth_date")
    op.drop_column("users", "last_name")
    op.drop_column("users", "first_name")
    op.drop_column("users", "github_username")
    op.drop_column("users", "github_id")
    GENDER_ENUM.drop(op.get_bind(), checkfirst=True)
```

> Verify the previous head with `venv/bin/alembic heads` and substitute the correct `down_revision`.

- [ ] **Step 2: Run pre-step + apply**

```bash
venv/bin/python scripts/reset_users.py
venv/bin/alembic upgrade head
```

Expected: 1 new column set added, no errors.

- [ ] **Step 3: Verify**

```bash
psql "postgresql://streamload:streamload@127.0.0.1:5432/streamload" -c "\d users"
```

Expected: github_id, github_username, first_name, last_name, birth_date, gender, profile_complete columns present; users count = 0.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/0009_github_auth.py
git commit -m "migration: add github_id + profile fields (first_name, last_name, birth_date, gender, profile_complete)"
```

---

### Task 2: Update SQLAlchemy User model + Pydantic UserPublic

**Files:**
- Modify: `streamload/db/models.py`
- Modify: `streamload/api/routes/auth.py` (UserPublic + _user_to_public)

- [ ] **Step 1: Add fields to the SQLAlchemy User model**

```python
# streamload/db/models.py — User class additions
import enum
import datetime as dt

class Gender(str, enum.Enum):
    male = "male"
    female = "female"
    non_binary = "non_binary"
    prefer_not_to_say = "prefer_not_to_say"


class User(Base):
    __tablename__ = "users"
    # ... existing fields ...
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    github_id: Mapped[int | None] = mapped_column(BigInteger, unique=True, nullable=True)
    github_username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    birth_date: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    gender: Mapped[Gender | None] = mapped_column(SQLEnum(Gender), nullable=True)
    profile_complete: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
```

> Match the imports the file already uses; add `BigInteger`, `Date`, `Boolean`, `Enum as SQLEnum` if missing.

- [ ] **Step 2: Update `UserPublic` and `_user_to_public` in `streamload/api/routes/auth.py`**

```python
class UserPublic(BaseModel):
    id: str
    username: str
    email: str
    email_verified: bool
    role: str
    github_username: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    birth_date: dt.date | None = None
    gender: str | None = None
    profile_complete: bool = False


def _user_to_public(u: User) -> UserPublic:
    return UserPublic(
        id=str(u.id),
        username=u.username,
        email=u.email,
        email_verified=u.email_verified_at is not None,
        role=u.role,
        github_username=u.github_username,
        first_name=u.first_name,
        last_name=u.last_name,
        birth_date=u.birth_date,
        gender=u.gender.value if u.gender else None,
        profile_complete=u.profile_complete,
    )
```

- [ ] **Step 3: Run existing auth tests, expect no regressions**

```bash
venv/bin/pytest tests/api/test_auth.py tests/api/test_me.py -x 2>&1 | tail -10
```

- [ ] **Step 4: Commit**

```bash
git add streamload/db/models.py streamload/api/routes/auth.py
git commit -m "models: add GitHub + profile fields to User; UserPublic exposes them"
```

---

### Task 3: `/api/auth/github` endpoint + GitHub OAuth helper

**Files:**
- Create: `streamload/auth/github.py`
- Create: `streamload/api/routes/auth_github.py`
- Modify: `streamload/api/app.py` — mount the new router
- Create: `tests/auth/test_github_oauth.py` + `tests/api/test_auth_github_endpoint.py`

- [ ] **Step 1: Write the helper test FIRST**

```python
# tests/auth/test_github_oauth.py
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
```

- [ ] **Step 2: Implement the helper**

```python
# streamload/auth/github.py
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
```

- [ ] **Step 3: Run helper tests**

```bash
venv/bin/pytest tests/auth/test_github_oauth.py -x 2>&1 | tail -5
```

- [ ] **Step 4: Write the endpoint test**

```python
# tests/api/test_auth_github_endpoint.py
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
```

- [ ] **Step 5: Implement the endpoint**

```python
# streamload/api/routes/auth_github.py
"""POST /api/auth/github — exchange a GitHub access token for a backend session."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

import httpx
from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from streamload.api.deps import SessionDep
from streamload.api.routes.auth import UserPublic, _user_to_public
from streamload.api.telemetry import emit as emit_event
from streamload.auth.github import fetch_github_profile
from streamload.auth.sessions import create_session
from streamload.db.models import User
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class GithubLoginRequest(BaseModel):
    access_token: str


@router.post("/github", status_code=200, response_model=UserPublic)
async def github_login(
    payload: GithubLoginRequest,
    db: SessionDep,
    response: Response,
    request: Request,
) -> UserPublic:
    async with httpx.AsyncClient(
        base_url="https://api.github.com", timeout=15
    ) as gh:
        try:
            profile = await fetch_github_profile(token=payload.access_token, http=gh)
        except ValueError as e:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e))

    # Find by github_id.
    user = (await db.execute(
        select(User).where(User.github_id == profile.id)
    )).scalar_one_or_none()

    if user is None:
        # Username must be unique; if profile.login collides with a legacy
        # password user, suffix with the github_id.
        username = profile.login
        existing = (await db.execute(
            select(User).where(User.username == username)
        )).scalar_one_or_none()
        if existing is not None:
            username = f"{profile.login}_{profile.id}"
        user = User(
            username=username,
            email=profile.email,
            password_hash=None,
            github_id=profile.id,
            github_username=profile.login,
            email_verified_at=datetime.now(UTC),
            email_required=False,
            role="user",
            profile_complete=False,
        )
        db.add(user)
        try:
            await db.commit()
            await db.refresh(user)
        except IntegrityError as e:
            await db.rollback()
            log.exception("github user create failed")
            raise HTTPException(status.HTTP_409_CONFLICT, str(e))
        await emit_event(db, request, user_id=user.id, event_type="auth.github_register",
                         payload={"github_id": profile.id})
        await db.commit()
    else:
        # Returning user — keep email + login fresh.
        user.github_username = profile.login
        user.email = profile.email
        await db.commit()
        await emit_event(db, request, user_id=user.id, event_type="auth.github_login",
                         payload={"github_id": profile.id})
        await db.commit()

    token = await create_session(
        db,
        user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session", token,
        httponly=True,
        secure=request.url.scheme == "https",
        samesite="lax",
        max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)
```

- [ ] **Step 6: Mount router in `streamload/api/app.py`**

Add the import:

```python
from streamload.api.routes.auth_github import router as auth_github_router
```

After the existing `app.include_router(auth_router, prefix="/api")`, add:

```python
app.include_router(auth_github_router, prefix="/api")
```

- [ ] **Step 7: Run all auth tests**

```bash
venv/bin/pytest tests/auth/ tests/api/test_auth.py tests/api/test_auth_github_endpoint.py -x 2>&1 | tail -10
```

Expected: all pass.

- [ ] **Step 8: Commit**

```bash
git add streamload/auth/github.py streamload/api/routes/auth_github.py streamload/api/app.py tests/auth/test_github_oauth.py tests/api/test_auth_github_endpoint.py
git commit -m "auth: POST /api/auth/github — exchange OAuth token for backend session (find-or-create)"
```

---

### Task 4: PATCH `/api/me/profile`

**Files:**
- Modify: `streamload/api/routes/me.py`
- Create: `tests/api/test_me_profile.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/api/test_me_profile.py
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def authed_github(api_client: httpx.AsyncClient, monkeypatch) -> dict:
    """Returns an api_client logged in as a fresh GitHub user (profile incomplete)."""

    async def fake_fetch(*, token, http):
        from streamload.auth.github import GithubProfile
        return GithubProfile(id=7, login="seven", email="seven@example.com",
                             name=None, avatar_url=None)

    monkeypatch.setattr(
        "streamload.api.routes.auth_github.fetch_github_profile", fake_fetch,
    )
    r = await api_client.post("/api/auth/github", json={"access_token": "x"})
    return r.json()


@pytest.mark.asyncio
async def test_patch_profile_marks_profile_complete(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "Andrea",
        "last_name": "Alfano",
        "birth_date": "1990-01-15",
        "gender": "male",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["first_name"] == "Andrea"
    assert body["last_name"] == "Alfano"
    assert body["birth_date"] == "1990-01-15"
    assert body["gender"] == "male"
    assert body["profile_complete"] is True


@pytest.mark.asyncio
async def test_patch_profile_rejects_unknown_gender(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "1990-01-01", "gender": "alien",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_profile_rejects_future_birth_date(api_client, authed_github):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "2099-01-01", "gender": "female",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_patch_profile_requires_session(api_client: httpx.AsyncClient):
    r = await api_client.patch("/api/me/profile", json={
        "first_name": "X", "last_name": "Y",
        "birth_date": "1990-01-01", "gender": "female",
    })
    assert r.status_code == 401
```

- [ ] **Step 2: Implement**

Add to `streamload/api/routes/me.py`:

```python
import datetime as dt
from pydantic import BaseModel, Field, field_validator
from streamload.db.models import Gender


class ProfilePatchRequest(BaseModel):
    first_name: str = Field(min_length=1, max_length=64)
    last_name: str = Field(min_length=1, max_length=64)
    birth_date: dt.date
    gender: str  # validated below

    @field_validator("birth_date")
    @classmethod
    def _not_future(cls, v: dt.date) -> dt.date:
        if v >= dt.date.today():
            raise ValueError("birth_date must be in the past")
        return v

    @field_validator("gender")
    @classmethod
    def _valid_gender(cls, v: str) -> str:
        if v not in {g.value for g in Gender}:
            raise ValueError(f"gender must be one of {[g.value for g in Gender]}")
        return v


@router.patch("/me/profile", status_code=200, response_model=UserPublic)
async def patch_profile(
    payload: ProfilePatchRequest,
    db: SessionDep,
    user: CurrentUser,
) -> UserPublic:
    user.first_name = payload.first_name
    user.last_name = payload.last_name
    user.birth_date = payload.birth_date
    user.gender = Gender(payload.gender)
    user.profile_complete = True
    await db.commit()
    await db.refresh(user)
    return _user_to_public(user)
```

> Reuse the existing `_user_to_public` from `auth.py` — import it: `from streamload.api.routes.auth import _user_to_public`.

- [ ] **Step 3: Run tests, expect 4 pass**

- [ ] **Step 4: Commit**

```bash
git add streamload/api/routes/me.py tests/api/test_me_profile.py
git commit -m "api: PATCH /api/me/profile — set first_name/last_name/birth_date/gender + mark complete"
```

---

## Phase B — Client domain + auth

### Task 5: Update `User` Dart model

**Files:**
- Modify: `lib/domain/models/user.dart`
- Run codegen

- [ ] **Step 1: Add fields**

```dart
@freezed
class User with _$User {
  const factory User({
    required String id,
    required String username,
    required String email,
    @JsonKey(name: 'email_verified') required bool emailVerified,
    @JsonKey(name: 'github_username') String? githubUsername,
    @JsonKey(name: 'first_name') String? firstName,
    @JsonKey(name: 'last_name') String? lastName,
    @JsonKey(name: 'birth_date') DateTime? birthDate,
    String? gender,
    @JsonKey(name: 'profile_complete') @Default(false) bool profileComplete,
  }) = _User;

  factory User.fromJson(Map<String, dynamic> json) => _$UserFromJson(json);
}
```

- [ ] **Step 2: Codegen**

```bash
dart run build_runner build --delete-conflicting-outputs
```

- [ ] **Step 3: Existing tests still pass**

```bash
flutter test 2>&1 | tail -3
```

- [ ] **Step 4: Commit**

```bash
git add lib/domain/models/user.dart lib/domain/models/user.freezed.dart lib/domain/models/user.g.dart
git commit -m "model: User adds githubUsername, firstName, lastName, birthDate, gender, profileComplete"
```

---

### Task 6: AuthApi — drop login/register, add loginWithGithub + updateProfile

**Files:**
- Modify: `lib/data/remote/endpoints/auth_api.dart`

- [ ] **Step 1: Replace the methods**

```dart
class AuthApi {
  AuthApi(this._client);
  final ApiClient _client;

  /// Exchange a GitHub OAuth access token for a backend session cookie.
  /// Returns the user (with profile_complete=false for first-time logins).
  Future<User> loginWithGithub(String accessToken) async {
    final json = await _client.postJson(
      '/api/auth/github',
      body: {'access_token': accessToken},
    );
    return User.fromJson(json);
  }

  Future<User> me() async {
    final json = await _client.getJson('/api/me');
    return User.fromJson(json);
  }

  Future<User> updateProfile({
    required String firstName,
    required String lastName,
    required DateTime birthDate,
    required String gender,
  }) async {
    final json = await _client.patchJson(
      '/api/me/profile',
      body: {
        'first_name': firstName,
        'last_name': lastName,
        'birth_date': birthDate.toIso8601String().substring(0, 10),
        'gender': gender,
      },
    );
    return User.fromJson(json);
  }

  Future<void> logout() async {
    await _client.postJson('/api/auth/logout');
  }
}
```

> If `ApiClient` doesn't have a `patchJson` method, add it (mirror `postJson` but use `dio.patch`).

- [ ] **Step 2: Run analyze + existing api tests, expect green**

- [ ] **Step 3: Commit**

```bash
git add lib/data/remote/endpoints/auth_api.dart lib/data/remote/api_client.dart
git commit -m "api(client): replace login/register with loginWithGithub + updateProfile"
```

---

### Task 7: AuthNotifier rewrite

**Files:**
- Modify: `lib/state/auth_provider.dart`

- [ ] **Step 1: Replace login/register methods on AuthNotifier**

The state shape stays as `sealed class AuthState { Loading, Unauthenticated, Authenticated(user), Error(msg) }`. Drop `login(username, password)` and `register(...)`. Add:

```dart
Future<void> loginWithGithub(String accessToken) async {
  state = const AuthLoading();
  try {
    final api = await ref.read(authApiProvider.future);
    final user = await api.loginWithGithub(accessToken);
    state = AuthAuthenticated(user: user);
  } catch (e) {
    state = AuthError(message: e.toString());
  }
}

Future<void> updateProfile({
  required String firstName,
  required String lastName,
  required DateTime birthDate,
  required String gender,
}) async {
  final current = state;
  if (current is! AuthAuthenticated) {
    throw StateError('updateProfile requires AuthAuthenticated state');
  }
  final api = await ref.read(authApiProvider.future);
  final user = await api.updateProfile(
    firstName: firstName, lastName: lastName,
    birthDate: birthDate, gender: gender,
  );
  state = AuthAuthenticated(user: user);
}
```

- [ ] **Step 2: Update existing AuthNotifier tests to match the new methods (delete login/register tests, add loginWithGithub success/failure tests).**

- [ ] **Step 3: Commit**

```bash
git add lib/state/auth_provider.dart test/state/auth_provider_test.dart
git commit -m "state: AuthNotifier — drop login/register, add loginWithGithub + updateProfile"
```

---

### Task 8: Delete `LoginPage` + `RegisterPage` + tests

**Files:**
- Delete: `lib/presentation/pages/login_page.dart`
- Delete: `lib/presentation/pages/register_page.dart`
- Delete: `test/pages/login_page_test.dart`
- Delete: `test/pages/register_page_test.dart`

- [ ] **Step 1: `git rm` the files**

```bash
git rm lib/presentation/pages/login_page.dart lib/presentation/pages/register_page.dart \
       test/pages/login_page_test.dart test/pages/register_page_test.dart
```

- [ ] **Step 2: Find and remove imports of the deleted files**

```bash
grep -rln "login_page\|register_page\|LoginPage\|RegisterPage" lib/ test/
```

Expected: only `lib/router.dart` references them. Leave for Task 12 (router rewrite).

- [ ] **Step 3: DO NOT commit yet** — the build is broken until router is updated. This is a "staging" task; bundle into Task 12's commit.

```bash
# leave staged but uncommitted
```

---

## Phase C — Onboarding + Profile

### Task 9: Update OAuth scope to include `user:email`

**Files:**
- Modify: `lib/plugins/github_oauth.dart`

- [ ] **Step 1: Bump default scope**

In `GithubOAuth.requestDeviceCode`:

```dart
Future<DeviceCodeRequest> requestDeviceCode({String scope = 'repo user:email'}) async {
```

- [ ] **Step 2: Update existing tests if they pin a scope** (the existing tests don't assert scope content; should be a no-op).

- [ ] **Step 3: Commit**

```bash
git add lib/plugins/github_oauth.dart
git commit -m "plugins: device flow scope now requests user:email so backend can read profile email"
```

---

### Task 10: Onboarding — call backend after device flow, route based on profile_complete

**Files:**
- Modify: `lib/presentation/pages/plugin_onboarding_page.dart`
- Update: `test/pages/plugin_onboarding_page_test.dart`

- [ ] **Step 1: Modify the success branch of `_start()`**

After `await ref.read(githubTokenProvider.notifier).save(token);`, add:

```dart
// Exchange the GitHub token for a backend session.
final user = await ref.read(authProvider.notifier).loginWithGithub(token);
// Plugin refresh in background regardless.
// ignore: unawaited_futures
ref.read(pluginRefreshControllerProvider.notifier).refresh();
if (!mounted) return;
final dest = (ref.read(authProvider) is AuthAuthenticated &&
              (ref.read(authProvider) as AuthAuthenticated).user.profileComplete)
    ? '/home'
    : '/onboarding/profile';
context.go(dest);
```

> If `loginWithGithub` returns a User directly, simpler: store it locally and check `user.profileComplete`. Adjust the AuthNotifier signature in T7 to also return the user.

- [ ] **Step 2: Update onboarding tests — mock both the OAuth factory AND the AuthNotifier; assert navigation goes to `/onboarding/profile` for profile_complete=false and `/home` for true.**

- [ ] **Step 3: Commit**

```bash
git add lib/presentation/pages/plugin_onboarding_page.dart test/pages/plugin_onboarding_page_test.dart
git commit -m "pages: onboarding — exchange GitHub token for backend session, route by profile_complete"
```

---

### Task 11: `ProfileCompletionPage`

**Files:**
- Create: `lib/presentation/pages/profile_completion_page.dart`
- Create: `test/pages/profile_completion_page_test.dart`

- [ ] **Step 1: Write the failing widget tests**

```dart
// test/pages/profile_completion_page_test.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:mocktail/mocktail.dart';
import 'package:streamload_client/data/remote/endpoints/auth_api.dart';
import 'package:streamload_client/domain/models/user.dart';
import 'package:streamload_client/presentation/pages/profile_completion_page.dart';
import 'package:streamload_client/state/auth_provider.dart';
import 'package:streamload_client/state/api_client_provider.dart';

class _AuthApiMock extends Mock implements AuthApi {}

void main() {
  testWidgets('submitting valid fields calls updateProfile and navigates home',
      (tester) async {
    final api = _AuthApiMock();
    when(() => api.updateProfile(
          firstName: any(named: 'firstName'),
          lastName: any(named: 'lastName'),
          birthDate: any(named: 'birthDate'),
          gender: any(named: 'gender'),
        )).thenAnswer((_) async => const User(
          id: 'u', username: 'u', email: 'u@x', emailVerified: true,
          firstName: 'Andrea', lastName: 'Alfano', gender: 'male',
          profileComplete: true,
        ));

    await tester.pumpWidget(ProviderScope(
      overrides: [
        authApiProvider.overrideWith((_) async => api),
        // pre-authenticated state (post-GitHub login):
        authProvider.overrideWith(() => _StubAuth(const User(
              id: 'u', username: 'u', email: 'u@x', emailVerified: true,
            ))),
      ],
      child: const MaterialApp(home: ProfileCompletionPage()),
    ));

    await tester.enterText(find.byKey(const Key('profile.first_name')), 'Andrea');
    await tester.enterText(find.byKey(const Key('profile.last_name')), 'Alfano');
    // birth_date + gender pickers omitted — assume defaults are valid
    await tester.tap(find.byKey(const Key('profile.submit')));
    await tester.pumpAndSettle();

    verify(() => api.updateProfile(
          firstName: 'Andrea', lastName: 'Alfano',
          birthDate: any(named: 'birthDate'),
          gender: any(named: 'gender'),
        )).called(1);
  });
}

// (StubAuth helper similar to other tests in the codebase)
```

- [ ] **Step 2: Implement the page**

```dart
// lib/presentation/pages/profile_completion_page.dart
import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';
import 'package:intl/intl.dart';

import '../../state/auth_provider.dart';
import '../theme/colors.dart';
import '../theme/typography.dart';
import '../widgets/eyebrow.dart';
import '../widgets/primary_button.dart';
import '../widgets/streamload_text_field.dart';

class ProfileCompletionPage extends ConsumerStatefulWidget {
  const ProfileCompletionPage({super.key});

  @override
  ConsumerState<ProfileCompletionPage> createState() => _State();
}

const _genderOptions = [
  ('male', 'Maschio'),
  ('female', 'Femmina'),
  ('non_binary', 'Non binario'),
  ('prefer_not_to_say', 'Preferisco non dirlo'),
];

class _State extends ConsumerState<ProfileCompletionPage> {
  final _formKey = GlobalKey<FormState>();
  final _first = TextEditingController();
  final _last = TextEditingController();
  DateTime? _birth;
  String? _gender;
  bool _busy = false;
  String? _error;

  Future<void> _pickDate() async {
    final now = DateTime.now();
    final picked = await showDatePicker(
      context: context,
      firstDate: DateTime(1900),
      lastDate: now,
      initialDate: DateTime(now.year - 25, now.month, now.day),
    );
    if (picked != null) setState(() => _birth = picked);
  }

  Future<void> _submit() async {
    if (!_formKey.currentState!.validate()) return;
    if (_birth == null || _gender == null) {
      setState(() => _error = 'Completa tutti i campi.');
      return;
    }
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      await ref.read(authProvider.notifier).updateProfile(
            firstName: _first.text.trim(),
            lastName: _last.text.trim(),
            birthDate: _birth!,
            gender: _gender!,
          );
      if (mounted) context.go('/home');
    } catch (e) {
      setState(() => _error = 'Errore: $e');
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  void dispose() {
    _first.dispose();
    _last.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 480),
          child: Padding(
            padding: const EdgeInsets.all(32),
            child: Form(
              key: _formKey,
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Eyebrow('Profilo'),
                  const SizedBox(height: 8),
                  Text('Completa il tuo profilo',
                      style: StreamloadTypography.display(fontSize: 32)),
                  const SizedBox(height: 24),
                  StreamloadTextField(
                    key: const Key('profile.first_name'),
                    controller: _first,
                    label: 'Nome',
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Inserisci il nome' : null,
                  ),
                  const SizedBox(height: 16),
                  StreamloadTextField(
                    key: const Key('profile.last_name'),
                    controller: _last,
                    label: 'Cognome',
                    validator: (v) =>
                        (v == null || v.trim().isEmpty) ? 'Inserisci il cognome' : null,
                  ),
                  const SizedBox(height: 16),
                  ListTile(
                    key: const Key('profile.birth_date'),
                    contentPadding: EdgeInsets.zero,
                    title: const Text('Data di nascita'),
                    subtitle: Text(_birth == null
                        ? 'Seleziona…'
                        : DateFormat('d MMMM yyyy', 'it').format(_birth!)),
                    trailing: const Icon(Icons.calendar_today),
                    onTap: _pickDate,
                  ),
                  const SizedBox(height: 16),
                  DropdownButtonFormField<String>(
                    key: const Key('profile.gender'),
                    decoration: const InputDecoration(
                      labelText: 'Genere',
                      border: OutlineInputBorder(),
                    ),
                    initialValue: _gender,
                    items: [
                      for (final (value, label) in _genderOptions)
                        DropdownMenuItem(value: value, child: Text(label)),
                    ],
                    onChanged: (v) => setState(() => _gender = v),
                  ),
                  if (_error != null) ...[
                    const SizedBox(height: 16),
                    Text(_error!,
                        style: StreamloadTypography.body(
                            fontSize: 13, color: StreamloadColors.critical)),
                  ],
                  const SizedBox(height: 24),
                  PrimaryButton(
                    key: const Key('profile.submit'),
                    label: _busy ? 'Salvataggio…' : 'Continua',
                    busy: _busy,
                    onPressed: _busy ? null : _submit,
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}
```

> If `intl` isn't already a dep, add `intl: ^0.19.0` to pubspec.

- [ ] **Step 3: Run tests + commit**

```bash
git add lib/presentation/pages/profile_completion_page.dart test/pages/profile_completion_page_test.dart pubspec.yaml pubspec.lock
git commit -m "pages: ProfileCompletionPage — Nome/Cognome/Data nascita/Genere"
```

---

### Task 12: Router rewrite — drop /login + /register, add /onboarding/profile

**Files:**
- Modify: `lib/router.dart`

- [ ] **Step 1: Drop the imports + routes for LoginPage and RegisterPage. Add ProfileCompletionPage. Update redirect:**

```dart
final routerProvider = Provider<GoRouter>((ref) {
  return GoRouter(
    initialLocation: '/onboarding/github',
    debugLogDiagnostics: false,
    redirect: (context, state) {
      final auth = ref.read(authProvider);
      final token = ref.read(githubTokenProvider).value;
      final loc = state.matchedLocation;
      final isOnboardingGithub = loc == '/onboarding/github';
      final isOnboardingProfile = loc == '/onboarding/profile';

      // No token at all → must do GitHub login first.
      if (token == null || token.isEmpty) {
        return isOnboardingGithub ? null : '/onboarding/github';
      }

      // Have token but no backend session yet → onboarding/github will
      // call loginWithGithub on submit; once authenticated this fires again.
      if (auth is! AuthAuthenticated) {
        if (auth is AuthLoading) return null;
        // AuthError or Unauthenticated with a token present — let
        // /onboarding/github surface the issue and the user can retry.
        return isOnboardingGithub ? null : '/onboarding/github';
      }

      // Authenticated. Check profile.
      if (!auth.user.profileComplete) {
        return isOnboardingProfile ? null : '/onboarding/profile';
      }

      // Fully ready — bounce out of onboarding pages.
      if (isOnboardingGithub || isOnboardingProfile) return '/home';
      return null;
    },
    refreshListenable: _RouterRefreshNotifier(ref),
    routes: [
      GoRoute(
        path: '/onboarding/github',
        builder: (_, __) => const PluginOnboardingPage(),
      ),
      GoRoute(
        path: '/onboarding/profile',
        builder: (_, __) => const ProfileCompletionPage(),
      ),
      ShellRoute(
        builder: (context, state, child) => AuthenticatedShell(child: child),
        routes: [
          GoRoute(path: '/home', builder: (_, __) => const HomePage()),
          GoRoute(path: '/library', builder: (_, __) => const LibraryPage()),
          GoRoute(path: '/search', builder: (_, __) => const SearchPage()),
          GoRoute(path: '/profile', builder: (_, __) => const ProfilePage()),
          GoRoute(path: '/settings', builder: (_, __) => const SettingsPage()),
          GoRoute(path: '/plugins', builder: (_, __) => const PluginsPage()),
          GoRoute(
            path: '/title/:tmdbId',
            builder: (ctx, state) => TitlePage(
              tmdbId: int.parse(state.pathParameters['tmdbId']!),
              mediaType: state.uri.queryParameters['media_type'] ?? 'movie',
            ),
          ),
          GoRoute(
            path: '/watch/:tmdbId',
            builder: (ctx, state) => WatchPlaceholderPage(
              tmdbId: int.parse(state.pathParameters['tmdbId']!),
              mediaType: state.uri.queryParameters['media_type'] ?? 'movie',
              season: int.tryParse(state.uri.queryParameters['season'] ?? ''),
              episode: int.tryParse(state.uri.queryParameters['episode'] ?? ''),
            ),
          ),
        ],
      ),
    ],
  );
});
```

> Drop the `import 'presentation/pages/login_page.dart';` and `register_page.dart` lines. Add `profile_completion_page.dart`.

- [ ] **Step 2: Run full suite, expect green** (this is the commit that bundles Task 8's `git rm`)

```bash
flutter test 2>&1 | tail -3
flutter analyze 2>&1 | tail -3
```

- [ ] **Step 3: Commit (bundles the Task 8 deletions)**

```bash
git add lib/router.dart
git commit -m "router: GitHub-only auth — drop /login + /register, add /onboarding/profile, gate /home on profile_complete"
```

---

## Acceptance criteria

- Backend: ~210 tests pass (~10 new across Phase A).
- Client: ~205 tests pass (~5 new minus ~10 deleted).
- `flutter analyze` clean. `pyright` (if used) clean.
- Operator runs `python scripts/reset_users.py` then `alembic upgrade head` cleanly.
- App startup with no token → `/onboarding/github` (single "Accedi con GitHub" button).
- Device flow → first time → `/onboarding/profile` → submit → `/home`.
- Restart with valid token + complete profile → straight to `/home`.
- `/login` and `/register` routes return 404 (or are simply absent from the router).
- A user with no plugin-repo access still completes onboarding + profile + lands on /home (browse-only mode from earlier OAuth plan still applies).

## Out of scope

- Email change flow (sticks with whatever GitHub returns for now).
- Avatar display from `avatar_url` (post-MVP polish).
- Token revocation on logout (clearing local state is enough).
- Fallback to username/password auth for dev users (covered by leaving the old `/api/auth/login` endpoint intact, but no UI surfaces it).
- Migrating existing user data — `scripts/reset_users.py` wipes dev users.
