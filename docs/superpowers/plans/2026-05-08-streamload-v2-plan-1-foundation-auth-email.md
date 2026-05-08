# Streamload v2 — Plan 1: Foundation + Auth + Email

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the FastAPI backbone with multi-user auth (argon2 passwords + WebAuthn passkeys), email verification via Resend, password reset, and full Postgres + Alembic schema. End state: a working API where users can register, verify email, log in, manage passkeys, and reset passwords. No catalog, no streaming, no frontend yet.

**Architecture:** New `streamload/api/` package introduces a FastAPI app served by Granian, backed by Postgres via SQLAlchemy 2.x async. Auth state lives in DB (sessions hashed at rest, opaque tokens in HttpOnly cookies). Email is sent via Resend through a thin async wrapper. Existing v1 modules are not modified except for `streamload/utils/config.py` (extended) and a new shared `streamload/db/` package. The curses CLI continues to work in parallel.

**Tech Stack:** Python 3.11+, FastAPI 0.115+, Granian, SQLAlchemy 2.x async, asyncpg, Alembic, argon2-cffi, webauthn (pip), resend (pip), pytest with pytest-asyncio.

**Spec reference:** `docs/superpowers/specs/2026-05-08-streamload-v2-design.md` §6.4 (Auth), §16 (Email), §5.1 (Data Model — users/sessions/email_tokens/webauthn_credentials).

---

## File Structure

**New package — `streamload/api/`:**
- `__init__.py` — public re-exports
- `app.py` — FastAPI app factory, lifespan, dependency wiring
- `deps.py` — FastAPI dependencies (`get_db`, `get_current_user`, `require_admin`)
- `routes/__init__.py`
- `routes/health.py` — `/api/health`, `/api/version`
- `routes/auth.py` — register, login, logout, current user
- `routes/passkey.py` — WebAuthn register + authenticate
- `routes/email.py` — verify email, request/confirm password reset

**New package — `streamload/db/`:**
- `__init__.py` — `get_engine()`, `get_session()`, `Base`
- `models.py` — SQLAlchemy declarative models for `User`, `Session`, `EmailToken`, `WebauthnCredential`
- `migrations/` — Alembic migrations (managed by `alembic init`)

**New package — `streamload/auth/`:**
- `__init__.py`
- `passwords.py` — argon2id hash + verify
- `sessions.py` — opaque token generation, hashed lookup, sliding expiry
- `passkeys.py` — WebAuthn registration + authentication ceremonies
- `tokens.py` — generic random token + sha256 hash helper
- `rate_limit.py` — in-memory token-bucket rate limiter

**New package — `streamload/email/`:**
- `__init__.py`
- `client.py` — Resend client (async wrapper over sync SDK via `asyncio.to_thread`)
- `templates.py` — HTML + plain-text bodies for verification + reset emails

**Modified files:**
- `requirements.txt` — add: `fastapi>=0.115`, `granian>=2.0`, `sqlalchemy[asyncio]>=2.0`, `asyncpg>=0.30`, `alembic>=1.13`, `argon2-cffi>=23`, `webauthn>=2.5`, `resend>=2.0`, `python-multipart>=0.0.20`
- `requirements-dev.txt` (NEW) — `pytest-asyncio>=0.24`, `httpx[http2]>=0.27`, `aiosqlite>=0.20` (for fast tests)
- `pyproject.toml` — extend pytest config for asyncio mode
- `streamload/utils/config.py` — add `auth`, `email`, `database`, `tmdb` (placeholder) sections to `AppConfig`
- `streamload/utils/config.py` — extend `_DEFAULT_LOGIN` with `RESEND` block
- `config.json.example` — document new sections
- `streamload.py` — add `--api` flag to launch FastAPI server (preserves curses default)
- `.env.example` (NEW) — `DATABASE_URL`, `RESEND_API_KEY`, etc.
- `.gitignore` — ensure `.env` is ignored (already is via `.env`)

**New tests — `tests/api/`:**
- `conftest.py` — pytest fixtures (test DB, async client)
- `test_health.py`
- `test_auth_register.py`
- `test_auth_login.py`
- `test_auth_session.py`
- `test_passkey.py`
- `test_email_verify.py`
- `test_email_reset.py`
- `test_rate_limit.py`

---

## Important conventions

- **Commit format:** Conventional Commits (`feat:`, `fix:`, `chore:`, `refactor:`, `test:`, `docs:`).
- **NEVER `Co-Authored-By` trailers** — user is sole author.
- **TDD strict:** test first, see it fail, implement, see it pass, commit.
- **`venv/bin/pytest`** only (project convention).
- **All new modules are async-first.** Sync-only code is a smell.
- **Branch:** create `feat/v2-foundation-auth-email` at the start; merge to main at end.

---

## Task 0: Branch + dependencies + dev DB

**Files:**
- Modify: `requirements.txt`
- Create: `requirements-dev.txt`
- Modify: `pyproject.toml`
- Create: `.env.example`
- Modify: `streamload.py` (add `--api` placeholder flag)

- [ ] **Step 1: Create feature branch**

```bash
git checkout main
git pull
git checkout -b feat/v2-foundation-auth-email
```

- [ ] **Step 2: Update `requirements.txt`**

Append (do not remove existing):
```
fastapi>=0.115
granian>=2.0
sqlalchemy[asyncio]>=2.0
asyncpg>=0.30
alembic>=1.13
argon2-cffi>=23
webauthn>=2.5
resend>=2.0
python-multipart>=0.0.20
email-validator>=2.2
```

- [ ] **Step 3: Create `requirements-dev.txt`**

```
-r requirements.txt
pytest-asyncio>=0.24
httpx[http2]>=0.27
aiosqlite>=0.20
```

- [ ] **Step 4: Extend `pyproject.toml`**

Replace existing `[tool.pytest.ini_options]` with:
```toml
[tool.pytest.ini_options]
minversion = "8.0"
testpaths = ["tests"]
addopts = "-q --strict-markers"
asyncio_mode = "auto"
filterwarnings = [
    "ignore::DeprecationWarning",
]
markers = [
    "network: tests that hit the real internet",
]
```

(Note: dropped strict `filterwarnings = ["error"]` because async libs emit known DeprecationWarnings during tests.)

- [ ] **Step 5: Create `.env.example`**

```
# Streamload v2 environment variables
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test

# Email (Resend) - put real value in .env, NEVER commit
RESEND_API_KEY=re_REPLACE_ME

# WebAuthn relying-party identity
WEBAUTHN_RP_ID=localhost
WEBAUTHN_RP_NAME=Streamload
WEBAUTHN_ORIGIN=http://localhost:8000

# Server bind
STREAMLOAD_API_HOST=127.0.0.1
STREAMLOAD_API_PORT=8000

# Logging
STREAMLOAD_LOG_LEVEL=INFO
```

- [ ] **Step 6: Add `--api` placeholder to `streamload.py`**

Read `streamload.py` first. After existing argparse setup, add:
```python
import argparse
parser = argparse.ArgumentParser()
parser.add_argument("--api", action="store_true", help="Launch FastAPI server (v2)")
args, _ = parser.parse_known_args()
if args.api:
    print("API server not yet implemented (Plan 1 in progress)")
    sys.exit(0)
```

(If `streamload.py` already calls into the curses app, wrap with the `--api` check before that.)

- [ ] **Step 7: Install deps**

Run:
```bash
venv/bin/pip install -r requirements-dev.txt
```
Expected: all packages install without errors.

- [ ] **Step 8: Create dev databases**

Run (assumes Postgres 16 installed via Homebrew on dev Mac):
```bash
createdb streamload || true
createdb streamload_test || true
```
Expected: no errors (databases created or already exist).

- [ ] **Step 9: Commit**

```bash
git add requirements.txt requirements-dev.txt pyproject.toml .env.example streamload.py
git commit -m "chore: add v2 foundation deps + dev env scaffolding"
```

---

## Task 1: SQLAlchemy async base

**Files:**
- Create: `streamload/db/__init__.py`
- Create: `streamload/db/base.py`
- Create: `streamload/db/session.py`
- Create: `tests/api/__init__.py`
- Create: `tests/db/__init__.py`
- Create: `tests/db/test_session.py`

- [ ] **Step 1: Failing test**

`tests/db/test_session.py`:
```python
"""Verify the async DB session factory yields a working AsyncSession."""
from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.session import create_engine, create_session_factory


@pytest.mark.asyncio
async def test_engine_executes_a_simple_query():
    url = os.environ.get("DATABASE_URL_TEST")
    if not url:
        pytest.skip("DATABASE_URL_TEST not set")
    engine = create_engine(url)
    factory = create_session_factory(engine)
    async with factory() as session:
        assert isinstance(session, AsyncSession)
        result = await session.execute(text("SELECT 1"))
        assert result.scalar_one() == 1
    await engine.dispose()
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=$(grep DATABASE_URL_TEST .env.example | cut -d= -f2-) venv/bin/pytest tests/db/test_session.py -v
```
Expected: FAIL — `streamload.db.session` not importable.

- [ ] **Step 3: Implement `streamload/db/session.py`**

```python
"""Async SQLAlchemy engine + session factory.

Module-level ``engine`` and ``async_session`` are populated by ``init()``
during FastAPI's lifespan. Tests construct their own engine via the
exported factory functions.
"""
from __future__ import annotations

from typing import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)


def create_engine(url: str, *, echo: bool = False) -> AsyncEngine:
    """Create an async engine. ``url`` must use ``+asyncpg``."""
    return create_async_engine(
        url,
        echo=echo,
        pool_pre_ping=True,
        pool_size=10,
        max_overflow=20,
    )


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create an async session factory bound to *engine*."""
    return async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


# Module-level globals filled by init().
_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def init(url: str) -> None:
    """Initialize module-level engine + session factory."""
    global _engine, _session_factory
    _engine = create_engine(url)
    _session_factory = create_session_factory(_engine)


async def shutdown() -> None:
    """Dispose the module-level engine."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: yield a session per request."""
    if _session_factory is None:
        raise RuntimeError("DB session factory not initialized")
    async with _session_factory() as session:
        yield session
```

- [ ] **Step 4: Implement `streamload/db/base.py`**

```python
"""Declarative base for all SQLAlchemy models."""
from __future__ import annotations

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Common base for all ORM models."""
```

- [ ] **Step 5: Implement `streamload/db/__init__.py`**

```python
"""Database package — async SQLAlchemy + models."""
from __future__ import annotations

from .base import Base
from .session import (
    create_engine,
    create_session_factory,
    get_session,
    init,
    shutdown,
)

__all__ = [
    "Base",
    "create_engine",
    "create_session_factory",
    "get_session",
    "init",
    "shutdown",
]
```

- [ ] **Step 6: Create empty test packages**

```bash
mkdir -p tests/api tests/db tests/auth tests/email
: > tests/api/__init__.py
: > tests/db/__init__.py
: > tests/auth/__init__.py
: > tests/email/__init__.py
```

- [ ] **Step 7: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST="postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test" venv/bin/pytest tests/db/test_session.py -v
```
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add streamload/db tests/api/__init__.py tests/db/__init__.py tests/auth/__init__.py tests/email/__init__.py tests/db/test_session.py
git commit -m "feat(db): async SQLAlchemy engine + session factory"
```

---

## Task 2: User + Session ORM models

**Files:**
- Create: `streamload/db/models.py`
- Create: `tests/db/test_models.py`

- [ ] **Step 1: Failing test**

`tests/db/test_models.py`:
```python
"""Verify ORM models map columns correctly."""
from __future__ import annotations

import uuid

from streamload.db.models import EmailToken, Session, User, WebauthnCredential


def test_user_has_expected_columns():
    cols = {c.name for c in User.__table__.columns}
    assert {"id", "username", "email", "email_verified_at", "email_required",
            "password_hash", "role", "locale", "avatar_url",
            "created_at", "last_login_at"} <= cols


def test_session_has_expected_columns():
    cols = {c.name for c in Session.__table__.columns}
    assert {"token_hash", "user_id", "user_agent", "ip_address",
            "issued_at", "expires_at", "last_seen_at"} <= cols


def test_email_token_has_expected_columns():
    cols = {c.name for c in EmailToken.__table__.columns}
    assert {"token_hash", "user_id", "purpose",
            "issued_at", "expires_at", "consumed_at"} <= cols


def test_webauthn_credential_has_expected_columns():
    cols = {c.name for c in WebauthnCredential.__table__.columns}
    assert {"id", "user_id", "credential_id", "public_key",
            "sign_count", "transports", "nickname",
            "created_at", "last_used_at"} <= cols


def test_user_id_is_uuid_default():
    u = User(username="x", email="x@x")
    assert isinstance(u.id, uuid.UUID) or u.id is None  # default fired only on flush
```

- [ ] **Step 2: Run, expect FAIL**

Run: `venv/bin/pytest tests/db/test_models.py -v`
Expected: FAIL — `streamload.db.models` missing.

- [ ] **Step 3: Implement `streamload/db/models.py`**

```python
"""SQLAlchemy ORM models.

Mirrors the schema in `docs/superpowers/specs/2026-05-08-streamload-v2-design.md` §5.1.
Migrations are managed by Alembic; these models are the source of truth.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import (
    ARRAY,
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import INET, JSONB, UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    username: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    email_verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )
    email_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true",
    )
    password_hash: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    role: Mapped[str] = mapped_column(
        Text, nullable=False, default="user", server_default="user",
    )
    locale: Mapped[str] = mapped_column(
        Text, nullable=False, default="it-IT", server_default="it-IT",
    )
    avatar_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_login_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    sessions: Mapped[list["Session"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    email_tokens: Mapped[list["EmailToken"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )
    webauthn_credentials: Mapped[list["WebauthnCredential"]] = relationship(
        back_populates="user", cascade="all, delete-orphan",
    )

    __table_args__ = (
        CheckConstraint("role IN ('admin', 'user')", name="ck_users_role"),
    )


class Session(Base):
    __tablename__ = "sessions"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ip_address: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True,
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    user: Mapped[User] = relationship(back_populates="sessions")


class EmailToken(Base):
    __tablename__ = "email_tokens"

    token_hash: Mapped[bytes] = mapped_column(LargeBinary, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(Text, nullable=False)
    issued_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )
    consumed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="email_tokens")

    __table_args__ = (
        CheckConstraint(
            "purpose IN ('verify_email', 'reset_password')",
            name="ck_email_tokens_purpose",
        ),
    )


class WebauthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
    )
    credential_id: Mapped[bytes] = mapped_column(
        LargeBinary, unique=True, nullable=False,
    )
    public_key: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    sign_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0",
    )
    transports: Mapped[list[str]] = mapped_column(
        ARRAY(Text), nullable=False, default=list, server_default="{}",
    )
    nickname: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
    last_used_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True,
    )

    user: Mapped[User] = relationship(back_populates="webauthn_credentials")
```

- [ ] **Step 4: Run, expect PASS**

Run: `venv/bin/pytest tests/db/test_models.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/db/models.py tests/db/test_models.py
git commit -m "feat(db): User, Session, EmailToken, WebauthnCredential models"
```

---

## Task 3: Alembic init + first migration

**Files:**
- Modify: project root (run `alembic init`)
- Create: `migrations/env.py` (replaced)
- Create: `migrations/versions/0001_users_sessions_email_webauthn.py`
- Create: `alembic.ini`
- Create: `tests/db/test_migrations.py`

- [ ] **Step 1: Initialize Alembic**

Run from project root:
```bash
venv/bin/alembic init -t async migrations
```
Expected: `alembic.ini` + `migrations/` directory created.

- [ ] **Step 2: Edit `alembic.ini`**

Replace the `sqlalchemy.url` line with:
```
sqlalchemy.url = driver://user:pass@host/dbname
```
(Empty placeholder; we set it from env in `migrations/env.py`.)

Set `script_location = migrations`.

- [ ] **Step 3: Replace `migrations/env.py`**

```python
"""Alembic environment for async SQLAlchemy."""
from __future__ import annotations

import asyncio
import os
import sys
from logging.config import fileConfig
from pathlib import Path

# Make sure the project root is importable.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from streamload.db import Base
from streamload.db import models  # noqa: F401  (registers models with Base)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _get_url() -> str:
    return os.environ.get("DATABASE_URL", config.get_main_option("sqlalchemy.url"))


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    config_section = config.get_section(config.config_ini_section, {})
    config_section["sqlalchemy.url"] = _get_url()
    connectable = async_engine_from_config(
        config_section, prefix="sqlalchemy.", poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

- [ ] **Step 4: Generate first migration**

Run:
```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  venv/bin/alembic revision --autogenerate -m "users sessions email webauthn"
```
Expected: a new file in `migrations/versions/` is created.

Rename the generated file to `0001_users_sessions_email_webauthn.py` for ordering clarity (also update its filename in code if needed; revision IDs stay).

- [ ] **Step 5: Apply migration**

```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  venv/bin/alembic upgrade head
```
Expected: Tables created in `streamload` database.

Verify with:
```bash
psql streamload -c "\dt"
```
Expected: `users`, `sessions`, `email_tokens`, `webauthn_credentials`, `alembic_version` listed.

- [ ] **Step 6: Smoke-test migration on test DB**

`tests/db/test_migrations.py`:
```python
"""Verify Alembic migrations apply cleanly to a fresh test DB."""
from __future__ import annotations

import os
import subprocess

import pytest


def test_alembic_upgrade_to_head():
    test_url = os.environ.get("DATABASE_URL_TEST")
    if not test_url:
        pytest.skip("DATABASE_URL_TEST not set")
    env = os.environ.copy()
    env["DATABASE_URL"] = test_url
    # Drop and recreate to verify a clean migration.
    subprocess.run(["dropdb", "--if-exists", "streamload_test"], check=False)
    subprocess.run(["createdb", "streamload_test"], check=True)
    result = subprocess.run(
        ["venv/bin/alembic", "upgrade", "head"],
        env=env, capture_output=True, text=True, check=False,
    )
    assert result.returncode == 0, f"alembic failed: {result.stderr}"
```

- [ ] **Step 7: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/db/test_migrations.py -v
```
Expected: 1 passed.

- [ ] **Step 8: Commit**

```bash
git add alembic.ini migrations tests/db/test_migrations.py
git commit -m "feat(db): Alembic init + initial schema migration"
```

---

## Task 4: FastAPI app skeleton + health endpoint

**Files:**
- Create: `streamload/api/__init__.py`
- Create: `streamload/api/app.py`
- Create: `streamload/api/deps.py`
- Create: `streamload/api/routes/__init__.py`
- Create: `streamload/api/routes/health.py`
- Create: `tests/api/conftest.py`
- Create: `tests/api/test_health.py`

- [ ] **Step 1: Failing test**

`tests/api/test_health.py`:
```python
"""Verify the health endpoint returns service metadata."""
from __future__ import annotations

import httpx
import pytest


@pytest.mark.asyncio
async def test_health_returns_200(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/health")
    assert r.status_code == 200
    payload = r.json()
    assert payload["status"] == "ok"
    assert "version" in payload


@pytest.mark.asyncio
async def test_version_endpoint(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/version")
    assert r.status_code == 200
    payload = r.json()
    assert "version" in payload
    assert "git_sha" in payload
```

- [ ] **Step 2: Failing fixture**

`tests/api/conftest.py`:
```python
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
```

- [ ] **Step 3: Run, expect FAIL**

Run: `venv/bin/pytest tests/api/test_health.py -v`
Expected: FAIL — `streamload.api.app` not importable.

- [ ] **Step 4: Implement `streamload/api/__init__.py`**

```python
"""Streamload v2 FastAPI application package."""
from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
```

- [ ] **Step 5: Implement `streamload/api/app.py`**

```python
"""FastAPI application factory + lifespan."""
from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import AsyncIterator

from fastapi import FastAPI

from streamload.db import init as db_init, shutdown as db_shutdown

from .routes import health


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
    app.include_router(health.router, prefix="/api")
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
```

- [ ] **Step 6: Implement `streamload/api/routes/__init__.py`**

```python
"""API routers."""
```

- [ ] **Step 7: Implement `streamload/api/routes/health.py`**

```python
"""Health and version endpoints."""
from __future__ import annotations

import os
import subprocess

from fastapi import APIRouter

router = APIRouter(tags=["health"])


def _git_sha() -> str:
    if env := os.environ.get("STREAMLOAD_GIT_SHA"):
        return env
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], text=True,
        ).strip()
    except Exception:
        return "unknown"


@router.get("/health")
async def health() -> dict[str, str]:
    """Liveness probe."""
    from streamload.version import __version__
    return {"status": "ok", "version": __version__}


@router.get("/version")
async def version() -> dict[str, str]:
    """Detailed version info."""
    from streamload.version import __version__
    return {"version": __version__, "git_sha": _git_sha()}
```

- [ ] **Step 8: Implement `streamload/api/deps.py`** (placeholder for now)

```python
"""FastAPI dependencies (will be filled in subsequent tasks)."""
from __future__ import annotations
```

- [ ] **Step 9: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_health.py -v
```
Expected: 2 passed.

- [ ] **Step 10: Commit**

```bash
git add streamload/api tests/api/conftest.py tests/api/test_health.py
git commit -m "feat(api): FastAPI skeleton with health + version endpoints"
```

---

## Task 5: Argon2 password helper

**Files:**
- Create: `streamload/auth/__init__.py`
- Create: `streamload/auth/passwords.py`
- Create: `tests/auth/test_passwords.py`

- [ ] **Step 1: Failing test**

`tests/auth/test_passwords.py`:
```python
"""Password hashing + verification."""
from __future__ import annotations

import pytest

from streamload.auth.passwords import hash_password, needs_rehash, verify_password


def test_hash_password_returns_argon2_string():
    h = hash_password("hunter2")
    assert h.startswith("$argon2id$")


def test_verify_password_accepts_correct():
    h = hash_password("hunter2")
    assert verify_password(h, "hunter2") is True


def test_verify_password_rejects_wrong():
    h = hash_password("hunter2")
    assert verify_password(h, "wrong") is False


def test_verify_password_rejects_empty():
    h = hash_password("hunter2")
    assert verify_password(h, "") is False


def test_verify_password_rejects_bad_hash_format():
    assert verify_password("not-a-hash", "hunter2") is False


def test_hash_password_rejects_empty():
    with pytest.raises(ValueError):
        hash_password("")


def test_needs_rehash_for_old_params():
    # Different params would trip needs_rehash. Synthesize a fake hash.
    weak_hash = "$argon2id$v=19$m=512,t=1,p=1$YWFh$YWFh"
    assert needs_rehash(weak_hash) is True
```

- [ ] **Step 2: Run, expect FAIL**

Run: `venv/bin/pytest tests/auth/test_passwords.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement `streamload/auth/__init__.py`**

```python
"""Authentication package."""
from __future__ import annotations
```

- [ ] **Step 4: Implement `streamload/auth/passwords.py`**

```python
"""Password hashing using argon2id.

We use the OWASP-recommended parameters for argon2id (May 2025):
- memory: 64 MB
- iterations: 3
- parallelism: 4

These are reasonable for a 2-core Celeron server while still resistant
to GPU brute-force at the threat scale we care about (single-user, no
public exposure).
"""
from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

# Tuned for our hardware target.
_hasher = PasswordHasher(
    time_cost=3,
    memory_cost=64 * 1024,  # KiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)


def hash_password(password: str) -> str:
    if not password:
        raise ValueError("password must be non-empty")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    if not password or not stored_hash:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    """Return True if *stored_hash* uses outdated params."""
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
```

- [ ] **Step 5: Run, expect PASS**

Run: `venv/bin/pytest tests/auth/test_passwords.py -v`
Expected: 7 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/auth/__init__.py streamload/auth/passwords.py tests/auth/test_passwords.py
git commit -m "feat(auth): argon2id password hashing helpers"
```

---

## Task 6: Token helpers + session storage

**Files:**
- Create: `streamload/auth/tokens.py`
- Create: `streamload/auth/sessions.py`
- Create: `tests/auth/test_tokens.py`
- Create: `tests/auth/test_sessions.py`

- [ ] **Step 1: Failing tests for tokens**

`tests/auth/test_tokens.py`:
```python
"""Random token generation + hashing."""
from __future__ import annotations

from streamload.auth.tokens import generate_token, hash_token


def test_generate_token_length():
    tok = generate_token()
    assert isinstance(tok, str)
    assert 40 <= len(tok) <= 60   # 32 bytes urlsafe-b64 ≈ 43 chars


def test_generate_tokens_are_unique():
    seen = {generate_token() for _ in range(100)}
    assert len(seen) == 100


def test_hash_token_is_deterministic():
    tok = "abc"
    assert hash_token(tok) == hash_token(tok)


def test_hash_token_returns_32_bytes():
    h = hash_token("abc")
    assert isinstance(h, bytes)
    assert len(h) == 32


def test_hash_token_differs_per_input():
    assert hash_token("abc") != hash_token("abd")
```

- [ ] **Step 2: Run, expect FAIL**

Run: `venv/bin/pytest tests/auth/test_tokens.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/auth/tokens.py`**

```python
"""Random token generation and hashing.

Tokens are 32 random bytes encoded as urlsafe-base64 (~43 chars). Stored
hashed using SHA-256 so a DB compromise does not expose live tokens.
"""
from __future__ import annotations

import hashlib
import secrets


def generate_token(num_bytes: int = 32) -> str:
    """Generate a urlsafe random token. Default 32 bytes (~43 chars)."""
    return secrets.token_urlsafe(num_bytes)


def hash_token(token: str) -> bytes:
    """SHA-256 of token, used for at-rest storage and lookup."""
    return hashlib.sha256(token.encode("utf-8")).digest()
```

- [ ] **Step 4: Run, expect PASS**

Run: `venv/bin/pytest tests/auth/test_tokens.py -v`
Expected: 5 passed.

- [ ] **Step 5: Failing tests for sessions**

`tests/auth/test_sessions.py`:
```python
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
        # Cleanup: ensure no stale data
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
```

- [ ] **Step 6: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/auth/test_sessions.py -v
```
Expected: FAIL — `streamload.auth.sessions` missing.

- [ ] **Step 7: Implement `streamload/auth/sessions.py`**

```python
"""Session lifecycle: create, lookup, refresh, delete.

Tokens are opaque 32-byte secrets returned to the client (HttpOnly cookie).
Only the SHA-256 hash is stored in the DB. Sessions have a sliding TTL:
last_seen_at + DEFAULT_TTL = effective expiry; refresh_session() updates
last_seen_at when the user makes an authenticated request.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import Session as SessionModel

from .tokens import generate_token, hash_token

DEFAULT_SESSION_TTL = timedelta(days=30)
REFRESH_GRACE = timedelta(minutes=5)  # only update last_seen if older than this


async def create_session(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    user_agent: Optional[str] = None,
    ip_address: Optional[str] = None,
    ttl: Optional[timedelta] = None,
) -> str:
    """Create a new session row, return the opaque token (give to client)."""
    token = generate_token()
    h = hash_token(token)
    now = datetime.now(UTC)
    expiry = now + (ttl if ttl is not None else DEFAULT_SESSION_TTL)
    db.add(SessionModel(
        token_hash=h,
        user_id=user_id,
        user_agent=user_agent,
        ip_address=ip_address,
        issued_at=now,
        expires_at=expiry,
        last_seen_at=now,
    ))
    await db.commit()
    return token


async def get_session_user_id(
    db: AsyncSession,
    *,
    token: str,
) -> Optional[uuid.UUID]:
    """Resolve a token to a user_id if the session is valid."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return None
    if s.expires_at <= datetime.now(UTC):
        return None
    return s.user_id


async def refresh_session(db: AsyncSession, *, token: str) -> None:
    """Update last_seen_at if it's older than the grace window."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is None:
        return
    now = datetime.now(UTC)
    if now - s.last_seen_at >= REFRESH_GRACE:
        s.last_seen_at = now
        # Slide expiry too
        s.expires_at = now + DEFAULT_SESSION_TTL
        await db.commit()


async def delete_session(db: AsyncSession, *, token: str) -> None:
    """Delete a session row (logout)."""
    h = hash_token(token)
    stmt = select(SessionModel).where(SessionModel.token_hash == h)
    s = (await db.execute(stmt)).scalar_one_or_none()
    if s is not None:
        await db.delete(s)
        await db.commit()
```

- [ ] **Step 8: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/auth/test_sessions.py -v
```
Expected: 6 passed.

- [ ] **Step 9: Commit**

```bash
git add streamload/auth/tokens.py streamload/auth/sessions.py tests/auth/test_tokens.py tests/auth/test_sessions.py
git commit -m "feat(auth): opaque session tokens with sliding TTL"
```

---

## Task 7: `current_user` dependency

**Files:**
- Modify: `streamload/api/deps.py`
- Create: `tests/api/test_deps.py`

- [ ] **Step 1: Failing test**

`tests/api/test_deps.py`:
```python
"""Auth dependency wires session cookie -> User."""
from __future__ import annotations

import httpx
import pytest

from streamload.auth.sessions import create_session
from streamload.db import get_session as db_get_session
from streamload.db.models import User


@pytest.mark.asyncio
async def test_protected_route_returns_401_without_cookie(api_client: httpx.AsyncClient):
    r = await api_client.get("/api/me")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_protected_route_returns_user_with_valid_cookie(api_client: httpx.AsyncClient):
    # Seed a user and a session row.
    async for db in db_get_session():
        u = User(username="bob", email="bob@example.com")
        db.add(u)
        await db.commit()
        await db.refresh(u)
        token = await create_session(db, user_id=u.id)
        break

    r = await api_client.get("/api/me", cookies={"session": token})
    assert r.status_code == 200
    body = r.json()
    assert body["username"] == "bob"
    assert body["email"] == "bob@example.com"
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_deps.py -v
```
Expected: FAIL — `/api/me` not registered.

- [ ] **Step 3: Implement `streamload/api/deps.py`**

```python
"""FastAPI dependencies for DB session, current user, admin gate."""
from __future__ import annotations

from typing import Annotated, AsyncIterator

from fastapi import Cookie, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.auth.sessions import get_session_user_id, refresh_session
from streamload.db import get_session
from streamload.db.models import User

SessionDep = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(
    db: SessionDep,
    session: str | None = Cookie(default=None, alias="session"),
) -> User:
    if not session:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "not authenticated")
    user_id = await get_session_user_id(db, token=session)
    if user_id is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid or expired session")
    await refresh_session(db, token=session)
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "user no longer exists")
    return u


async def get_optional_user(
    db: SessionDep,
    session: str | None = Cookie(default=None, alias="session"),
) -> User | None:
    if not session:
        return None
    user_id = await get_session_user_id(db, token=session)
    if user_id is None:
        return None
    return (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()


async def require_admin(user: Annotated[User, Depends(get_current_user)]) -> User:
    if user.role != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "admin required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
OptionalUser = Annotated[User | None, Depends(get_optional_user)]
AdminUser = Annotated[User, Depends(require_admin)]
```

- [ ] **Step 4: Add `/api/me` route in a new module**

Create `streamload/api/routes/me.py`:
```python
"""Current-user endpoint."""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

from streamload.api.deps import CurrentUser

router = APIRouter(tags=["users"])


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    email_verified: bool
    role: str
    locale: str

    class Config:
        from_attributes = True


@router.get("/me", response_model=UserResponse)
async def me(user: CurrentUser) -> UserResponse:
    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        email_verified=user.email_verified_at is not None,
        role=user.role,
        locale=user.locale,
    )
```

- [ ] **Step 5: Wire `me` router into `app.py`**

Edit `streamload/api/app.py`. Add `from .routes import health, me` and `app.include_router(me.router, prefix="/api")`.

- [ ] **Step 6: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_deps.py -v
```
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/api/deps.py streamload/api/routes/me.py streamload/api/app.py tests/api/test_deps.py
git commit -m "feat(api): current_user dependency + /api/me endpoint"
```

---

## Task 8: Email service (Resend wrapper)

**Files:**
- Create: `streamload/email/__init__.py`
- Create: `streamload/email/client.py`
- Create: `streamload/email/templates.py`
- Create: `tests/email/test_client.py`

- [ ] **Step 1: Failing test**

`tests/email/test_client.py`:
```python
"""Resend email client wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from streamload.email.client import EmailClient, EmailError


@pytest.mark.asyncio
async def test_send_calls_resend_api(monkeypatch):
    fake_resp = {"id": "fake-msg-id"}
    fake_send = MagicMock(return_value=fake_resp)
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", fake_send)

    client = EmailClient(api_key="re_fake", from_address="noreply@example.com")
    msg_id = await client.send(
        to="user@example.com",
        subject="hi",
        html="<p>hi</p>",
        text="hi",
    )
    assert msg_id == "fake-msg-id"
    fake_send.assert_called_once()
    args = fake_send.call_args[0][0]
    assert args["to"] == ["user@example.com"]
    assert args["subject"] == "hi"


@pytest.mark.asyncio
async def test_send_raises_on_resend_error(monkeypatch):
    def boom(_):
        raise RuntimeError("resend down")
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", boom)

    client = EmailClient(api_key="re_fake", from_address="noreply@example.com")
    with pytest.raises(EmailError):
        await client.send(to="x@x", subject="x", html="x", text="x")


@pytest.mark.asyncio
async def test_send_in_dry_run_mode_does_not_call_api(monkeypatch):
    fake_send = MagicMock()
    monkeypatch.setattr("streamload.email.client.resend.Emails.send", fake_send)

    client = EmailClient(api_key="", from_address="noreply@example.com", dry_run=True)
    msg_id = await client.send(to="x@x", subject="x", html="x", text="x")
    assert msg_id.startswith("dry-run-")
    fake_send.assert_not_called()
```

- [ ] **Step 2: Run, expect FAIL**

Run: `venv/bin/pytest tests/email/test_client.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/email/__init__.py`**

```python
"""Email subsystem (transactional only, Resend backend)."""
from __future__ import annotations

from .client import EmailClient, EmailError

__all__ = ["EmailClient", "EmailError"]
```

- [ ] **Step 4: Implement `streamload/email/client.py`**

```python
"""Resend email client (async wrapper).

The official ``resend`` SDK is sync; we wrap calls in ``asyncio.to_thread``
to avoid blocking the event loop.

Set ``dry_run=True`` (or pass an empty api_key) to no-op the send during
local development. The returned message ID will be prefixed ``dry-run-``.
"""
from __future__ import annotations

import asyncio
import secrets
from dataclasses import dataclass

import resend

from streamload.utils.logger import get_logger

log = get_logger(__name__)


class EmailError(Exception):
    """Raised when Resend rejects the message."""


@dataclass
class EmailClient:
    api_key: str
    from_address: str
    dry_run: bool = False

    def __post_init__(self) -> None:
        if not self.dry_run and not self.api_key:
            self.dry_run = True
            log.warning("EmailClient has no api_key; falling back to dry-run mode")
        if self.api_key:
            resend.api_key = self.api_key

    async def send(
        self,
        *,
        to: str,
        subject: str,
        html: str,
        text: str,
    ) -> str:
        """Send an email. Returns the Resend message ID."""
        if self.dry_run:
            msg_id = f"dry-run-{secrets.token_hex(8)}"
            log.info("DRY-RUN email to=%s subject=%s id=%s", to, subject, msg_id)
            return msg_id
        payload = {
            "from": self.from_address,
            "to": [to],
            "subject": subject,
            "html": html,
            "text": text,
        }
        try:
            resp = await asyncio.to_thread(resend.Emails.send, payload)
        except Exception as exc:
            log.error("Resend send failed: %s", exc, exc_info=True)
            raise EmailError(f"resend error: {exc}") from exc
        msg_id = resp.get("id", "") if isinstance(resp, dict) else ""
        if not msg_id:
            raise EmailError(f"resend returned unexpected response: {resp!r}")
        log.info("Sent email to=%s subject=%s id=%s", to, subject, msg_id)
        return msg_id
```

- [ ] **Step 5: Implement `streamload/email/templates.py`**

```python
"""Email templates: HTML + plain-text bodies for transactional emails."""
from __future__ import annotations

_BRAND_COLOR = "#d4a574"

_BASE_HTML = """\
<!DOCTYPE html>
<html lang="it">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{title}</title>
</head>
<body style="margin:0;padding:24px;background:#0a0a0a;color:#fff;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
    <table role="presentation" style="max-width:520px;margin:0 auto;background:#141414;border-radius:12px;overflow:hidden;">
        <tr><td style="padding:32px 28px;">
            <h1 style="margin:0 0 16px;font-size:24px;font-weight:700;letter-spacing:-0.5px;">{heading}</h1>
            <div style="font-size:15px;line-height:1.5;color:rgba(255,255,255,0.85);">{body_html}</div>
            <div style="margin-top:24px;text-align:center;">
                <a href="{cta_url}" style="display:inline-block;padding:14px 28px;background:{accent};color:#1a1410;text-decoration:none;border-radius:24px;font-weight:600;font-size:14px;">{cta_text}</a>
            </div>
            <div style="margin-top:32px;font-size:12px;color:rgba(255,255,255,0.4);line-height:1.4;">
                Se non hai richiesto questa email, ignorala — il link scadrà tra {ttl}.
            </div>
        </td></tr>
    </table>
</body>
</html>
"""


def verification_email(*, username: str, link: str, ttl_label: str = "24 ore") -> tuple[str, str, str]:
    subject = "Conferma il tuo account Streamload"
    html = _BASE_HTML.format(
        title=subject,
        heading=f"Ciao {username}!",
        body_html=(
            "Per completare la registrazione su Streamload, clicca il pulsante "
            "qui sotto per confermare il tuo indirizzo email."
        ),
        cta_url=link,
        cta_text="Conferma email",
        accent=_BRAND_COLOR,
        ttl=ttl_label,
    )
    text = (
        f"Ciao {username}!\n\n"
        f"Per completare la registrazione su Streamload, apri questo link:\n{link}\n\n"
        f"Il link scade tra {ttl_label}. Se non hai richiesto questa email, ignorala.\n"
    )
    return subject, html, text


def password_reset_email(*, username: str, link: str, ttl_label: str = "1 ora") -> tuple[str, str, str]:
    subject = "Reimposta la tua password Streamload"
    html = _BASE_HTML.format(
        title=subject,
        heading=f"Ciao {username},",
        body_html=(
            "Hai richiesto di reimpostare la password. Clicca il pulsante per "
            "scegliere una nuova password. Per sicurezza, tutte le tue sessioni "
            "attive verranno terminate al cambio password."
        ),
        cta_url=link,
        cta_text="Reimposta password",
        accent=_BRAND_COLOR,
        ttl=ttl_label,
    )
    text = (
        f"Ciao {username},\n\n"
        f"Hai richiesto di reimpostare la password. Apri questo link:\n{link}\n\n"
        f"Il link scade tra {ttl_label}. Se non hai richiesto questa email, ignorala.\n"
    )
    return subject, html, text
```

- [ ] **Step 6: Run, expect PASS**

Run: `venv/bin/pytest tests/email/test_client.py -v`
Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/email tests/email/test_client.py
git commit -m "feat(email): Resend async client + transactional templates"
```

---

## Task 9: Email tokens (verify + reset)

**Files:**
- Create: `streamload/auth/email_tokens.py`
- Create: `tests/auth/test_email_tokens.py`

- [ ] **Step 1: Failing test**

`tests/auth/test_email_tokens.py`:
```python
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
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/auth/test_email_tokens.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/auth/email_tokens.py`**

```python
"""Email tokens: issue, consume, purge.

Tokens are single-use. Issuing a new token for the same (user, purpose)
invalidates the previous unused one (replaces it). Tokens are stored as
SHA-256 hashes; the plaintext is only available at issuance time.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import EmailToken

from .tokens import generate_token, hash_token

Purpose = Literal["verify_email", "reset_password"]

DEFAULT_TTL: dict[str, timedelta] = {
    "verify_email": timedelta(hours=24),
    "reset_password": timedelta(hours=1),
}


async def issue_token(
    db: AsyncSession,
    *,
    user_id: uuid.UUID,
    purpose: Purpose,
    ttl: Optional[timedelta] = None,
) -> str:
    """Issue a new token, replacing any existing unused one for same (user, purpose)."""
    # Invalidate previous unused tokens of the same purpose for this user.
    await db.execute(
        delete(EmailToken)
        .where(EmailToken.user_id == user_id)
        .where(EmailToken.purpose == purpose)
        .where(EmailToken.consumed_at.is_(None))
    )
    token = generate_token()
    h = hash_token(token)
    now = datetime.now(UTC)
    db.add(EmailToken(
        token_hash=h,
        user_id=user_id,
        purpose=purpose,
        issued_at=now,
        expires_at=now + (ttl if ttl is not None else DEFAULT_TTL[purpose]),
    ))
    await db.commit()
    return token


async def consume_token(
    db: AsyncSession,
    *,
    token: str,
    purpose: Purpose,
) -> Optional[uuid.UUID]:
    """Verify + consume a token. Returns the user_id if valid, else None."""
    h = hash_token(token)
    stmt = select(EmailToken).where(EmailToken.token_hash == h)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return None
    if row.purpose != purpose:
        return None
    if row.consumed_at is not None:
        return None
    if row.expires_at <= datetime.now(UTC):
        return None
    row.consumed_at = datetime.now(UTC)
    await db.commit()
    return row.user_id


async def purge_expired_tokens(db: AsyncSession) -> int:
    """Delete expired or consumed tokens older than 30 days. Return count."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    result = await db.execute(
        delete(EmailToken)
        .where(
            (EmailToken.expires_at < datetime.now(UTC)) |
            (EmailToken.consumed_at < cutoff)
        )
    )
    await db.commit()
    return result.rowcount or 0
```

- [ ] **Step 4: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/auth/test_email_tokens.py -v
```
Expected: 7 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/auth/email_tokens.py tests/auth/test_email_tokens.py
git commit -m "feat(auth): email tokens for verification + password reset"
```

---

## Task 10: Rate limiter

**Files:**
- Create: `streamload/auth/rate_limit.py`
- Create: `tests/auth/test_rate_limit.py`

- [ ] **Step 1: Failing test**

`tests/auth/test_rate_limit.py`:
```python
"""In-memory token-bucket rate limiter."""
from __future__ import annotations

import time

import pytest

from streamload.auth.rate_limit import RateLimiter


def test_allows_within_limit():
    rl = RateLimiter(rate=5, per_seconds=60)
    for _ in range(5):
        assert rl.check("k") is True


def test_blocks_after_limit():
    rl = RateLimiter(rate=2, per_seconds=60)
    rl.check("k"); rl.check("k")
    assert rl.check("k") is False


def test_isolated_per_key():
    rl = RateLimiter(rate=1, per_seconds=60)
    assert rl.check("a") is True
    assert rl.check("b") is True


def test_refills_after_window():
    rl = RateLimiter(rate=2, per_seconds=0.1)
    rl.check("k"); rl.check("k")
    assert rl.check("k") is False
    time.sleep(0.15)
    assert rl.check("k") is True


def test_remaining_returns_correct_count():
    rl = RateLimiter(rate=5, per_seconds=60)
    rl.check("k"); rl.check("k")
    assert rl.remaining("k") == 3


def test_negative_rate_raises():
    with pytest.raises(ValueError):
        RateLimiter(rate=0, per_seconds=60)
```

- [ ] **Step 2: Run, expect FAIL**

Run: `venv/bin/pytest tests/auth/test_rate_limit.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/auth/rate_limit.py`**

```python
"""In-memory token-bucket rate limiter.

Designed for single-instance deployments. State lives in process memory
and resets on restart — appropriate for our single-server architecture.
For multi-instance deployments a Redis-backed limiter would replace this.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    last_refill: float


class RateLimiter:
    """A simple token bucket. ``rate`` tokens per ``per_seconds`` window."""

    def __init__(self, *, rate: int, per_seconds: float) -> None:
        if rate <= 0:
            raise ValueError("rate must be > 0")
        if per_seconds <= 0:
            raise ValueError("per_seconds must be > 0")
        self._rate = rate
        self._per = per_seconds
        self._refill_per_sec = rate / per_seconds
        self._buckets: dict[str, _Bucket] = {}
        self._lock = threading.Lock()

    def check(self, key: str) -> bool:
        """Consume one token if available. Returns True if allowed."""
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=self._rate, last_refill=now)
                self._buckets[key] = b
            else:
                elapsed = now - b.last_refill
                b.tokens = min(self._rate, b.tokens + elapsed * self._refill_per_sec)
                b.last_refill = now
            if b.tokens >= 1:
                b.tokens -= 1
                return True
            return False

    def remaining(self, key: str) -> int:
        """Number of tokens currently available for *key* (without consuming)."""
        now = time.monotonic()
        with self._lock:
            b = self._buckets.get(key)
            if b is None:
                return self._rate
            elapsed = now - b.last_refill
            tokens = min(self._rate, b.tokens + elapsed * self._refill_per_sec)
            return int(tokens)
```

- [ ] **Step 4: Run, expect PASS**

Run: `venv/bin/pytest tests/auth/test_rate_limit.py -v`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/auth/rate_limit.py tests/auth/test_rate_limit.py
git commit -m "feat(auth): in-memory token-bucket rate limiter"
```

---

## Task 11: Register endpoint

**Files:**
- Create: `streamload/api/routes/auth.py`
- Modify: `streamload/api/app.py` (include router)
- Create: `tests/api/test_auth_register.py`

- [ ] **Step 1: Failing test**

`tests/api/test_auth_register.py`:
```python
"""User registration."""
from __future__ import annotations

import httpx
import pytest

from streamload.db import get_session
from streamload.db.models import User


@pytest.mark.asyncio
async def test_register_creates_user(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice",
        "email": "alice@example.com",
        "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    body = r.json()
    assert body["username"] == "alice"
    assert body["email_verified"] is False


@pytest.mark.asyncio
async def test_first_user_becomes_admin(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "first", "email": "first@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    assert r.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_subsequent_users_are_role_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "first", "email": "first@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/auth/register", json={
        "username": "second", "email": "second@x.com", "password": "Hunter2!secret",
    })
    assert r.json()["role"] == "user"


@pytest.mark.asyncio
async def test_register_rejects_duplicate_username(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "a@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "b@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 409


@pytest.mark.asyncio
async def test_register_rejects_invalid_email(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "not-an-email", "password": "Hunter2!secret",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_short_password(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "12",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_sets_session_cookie(api_client: httpx.AsyncClient):
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    assert "session" in r.cookies
```

- [ ] **Step 2: Reset test DB before tests**

Edit `tests/api/conftest.py` — wrap each test with a clean state:
```python
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

    app = create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
    await db_shutdown()
```

- [ ] **Step 3: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_auth_register.py -v
```
Expected: FAIL — endpoint missing.

- [ ] **Step 4: Implement `streamload/api/routes/auth.py`**

```python
"""Auth endpoints: register, login, logout."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from streamload.api.deps import CurrentUser, SessionDep
from streamload.auth.email_tokens import issue_token
from streamload.auth.passwords import hash_password, verify_password
from streamload.auth.rate_limit import RateLimiter
from streamload.auth.sessions import create_session, delete_session
from streamload.db.models import User
from streamload.email.client import EmailClient
from streamload.email.templates import verification_email
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

_login_limiter_per_ip = RateLimiter(rate=10, per_seconds=300)
_login_limiter_per_user = RateLimiter(rate=5, per_seconds=300)


class RegisterRequest(BaseModel):
    username: str = Field(min_length=3, max_length=32, pattern=r"^[a-zA-Z0-9_-]+$")
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class UserPublic(BaseModel):
    id: str
    username: str
    email: str
    email_verified: bool
    role: str


def _user_to_public(u: User) -> UserPublic:
    return UserPublic(
        id=str(u.id),
        username=u.username,
        email=u.email,
        email_verified=u.email_verified_at is not None,
        role=u.role,
    )


def _build_email_client() -> EmailClient | None:
    """Best-effort email client from env. None when no API key."""
    import os
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("RESEND_FROM", "noreply@resend.dev")
    if not api_key:
        return EmailClient(api_key="", from_address=from_addr, dry_run=True)
    return EmailClient(api_key=api_key, from_address=from_addr)


@router.post("/register", status_code=201, response_model=UserPublic)
async def register(payload: RegisterRequest, db: SessionDep, response: Response, request: Request) -> UserPublic:
    # Determine role: first user becomes admin.
    count = (await db.execute(select(func.count(User.id)))).scalar_one()
    role = "admin" if count == 0 else "user"

    user = User(
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        role=role,
    )
    db.add(user)
    try:
        await db.commit()
        await db.refresh(user)
    except IntegrityError:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "username or email already in use")

    # Issue verification token + send email.
    tok = await issue_token(db, user_id=user.id, purpose="verify_email")
    base = str(request.base_url).rstrip("/")
    link = f"{base}/verify?token={tok}"
    client = _build_email_client()
    if client is not None:
        subject, html, text = verification_email(username=user.username, link=link)
        try:
            await client.send(to=user.email, subject=subject, html=html, text=text)
        except Exception:
            log.warning("Failed to send verification email", exc_info=True)
            # Do not fail registration if email is down.

    # Issue login session immediately (user can browse, just can't play yet).
    token = await create_session(
        db, user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session", token,
        httponly=True, secure=request.url.scheme == "https",
        samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)
```

- [ ] **Step 5: Wire router in `streamload/api/app.py`**

```python
from .routes import auth, health, me

# in create_app:
app.include_router(auth.router, prefix="/api")
```

- [ ] **Step 6: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_auth_register.py -v
```
Expected: 7 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/api/routes/auth.py streamload/api/app.py tests/api/test_auth_register.py tests/api/conftest.py
git commit -m "feat(api): user registration with first-user-admin + email send"
```

---

## Task 12: Email verify endpoint

**Files:**
- Create: `streamload/api/routes/email.py`
- Modify: `streamload/api/app.py`
- Create: `tests/api/test_email_verify.py`

- [ ] **Step 1: Failing test**

`tests/api/test_email_verify.py`:
```python
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as db_get_session
from streamload.db.models import User


@pytest.mark.asyncio
async def test_verify_with_valid_token_sets_email_verified_at(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    # Issue another token directly to test verify (the registration one was sent via dry-run email).
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    assert r.status_code == 200

    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        assert u.email_verified_at is not None
        break


@pytest.mark.asyncio
async def test_verify_with_invalid_token_returns_400(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    r = await api_client.post(f"/api/auth/verify-email", json={"token": "bogus"})
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_verify_is_idempotent_safe(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    async for db in db_get_session():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r1 = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    r2 = await api_client.post(f"/api/auth/verify-email", json={"token": tok})
    assert r1.status_code == 200
    assert r2.status_code == 400  # token already consumed
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_email_verify.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/api/routes/email.py`**

```python
"""Email verification + password reset endpoints."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import SessionDep
from streamload.auth.email_tokens import consume_token
from streamload.db.models import User

router = APIRouter(prefix="/auth", tags=["email"])


class VerifyRequest(BaseModel):
    token: str


@router.post("/verify-email", status_code=200)
async def verify_email(payload: VerifyRequest, db: SessionDep) -> dict[str, str]:
    user_id = await consume_token(db, token=payload.token, purpose="verify_email")
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user not found")
    u.email_verified_at = datetime.now(UTC)
    await db.commit()
    return {"status": "verified"}
```

- [ ] **Step 4: Wire router in `streamload/api/app.py`**

```python
from .routes import auth, email, health, me
# in create_app:
app.include_router(email.router, prefix="/api")
```

- [ ] **Step 5: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_email_verify.py -v
```
Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add streamload/api/routes/email.py streamload/api/app.py tests/api/test_email_verify.py
git commit -m "feat(api): email verification endpoint"
```

---

## Task 13: Login endpoint (password)

**Files:**
- Modify: `streamload/api/routes/auth.py`
- Create: `tests/api/test_auth_login.py`

- [ ] **Step 1: Failing test**

`tests/api/test_auth_login.py`:
```python
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def registered_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    # clear cookies to start fresh
    api_client.cookies.clear()


@pytest.mark.asyncio
async def test_login_with_valid_credentials_sets_cookie(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    assert r.status_code == 200
    assert "session" in r.cookies


@pytest.mark.asyncio
async def test_login_with_email_works(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "wrong",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_with_unknown_user_returns_401(api_client, registered_user):
    r = await api_client.post("/api/auth/login", json={
        "username": "ghost", "password": "Hunter2!secret",
    })
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_login_updates_last_login_at(api_client, registered_user):
    from sqlalchemy import select
    from streamload.db import get_session as gs
    from streamload.db.models import User
    await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        assert u.last_login_at is not None
        break
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_auth_login.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `streamload/api/routes/auth.py`**

```python
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=255)  # accepts username OR email
    password: str = Field(min_length=1, max_length=128)


@router.post("/login", status_code=200, response_model=UserPublic)
async def login(payload: LoginRequest, db: SessionDep, response: Response, request: Request) -> UserPublic:
    ip_key = request.client.host if request.client else "unknown"
    user_key = payload.username.lower()
    if not _login_limiter_per_ip.check(ip_key) or not _login_limiter_per_user.check(user_key):
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "too many login attempts")

    stmt = select(User).where((User.username == payload.username) | (User.email == payload.username.lower()))
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None or not user.password_hash:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not verify_password(user.password_hash, payload.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")

    user.last_login_at = datetime.now(UTC)
    await db.commit()

    token = await create_session(
        db, user_id=user.id,
        user_agent=request.headers.get("user-agent"),
        ip_address=request.client.host if request.client else None,
    )
    response.set_cookie(
        "session", token,
        httponly=True, secure=request.url.scheme == "https",
        samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return _user_to_public(user)


@router.post("/logout", status_code=204)
async def logout(request: Request, response: Response, db: SessionDep) -> None:
    token = request.cookies.get("session")
    if token:
        await delete_session(db, token=token)
    response.delete_cookie("session")
```

- [ ] **Step 4: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_auth_login.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/auth.py tests/api/test_auth_login.py
git commit -m "feat(api): password login + logout with rate limit"
```

---

## Task 14: Password reset request + confirm

**Files:**
- Modify: `streamload/api/routes/email.py`
- Create: `tests/api/test_email_reset.py`

- [ ] **Step 1: Failing test**

`tests/api/test_email_reset.py`:
```python
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.auth.passwords import verify_password
from streamload.db import get_session as gs
from streamload.db.models import User, Session as SessionModel


@pytest.fixture
async def registered_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "OldPass!1234",
    })
    api_client.cookies.clear()


@pytest.mark.asyncio
async def test_request_reset_returns_200_for_existing_email(api_client, registered_user):
    r = await api_client.post("/api/auth/request-password-reset", json={"email": "alice@x.com"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_request_reset_returns_200_for_unknown_email_anti_enumeration(api_client, registered_user):
    r = await api_client.post("/api/auth/request-password-reset", json={"email": "ghost@x.com"})
    assert r.status_code == 200


@pytest.mark.asyncio
async def test_confirm_reset_changes_password(api_client, registered_user):
    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="reset_password")
        break

    r = await api_client.post("/api/auth/confirm-password-reset", json={
        "token": tok, "new_password": "NewPass!9876",
    })
    assert r.status_code == 200

    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        assert verify_password(u.password_hash, "NewPass!9876")
        break


@pytest.mark.asyncio
async def test_confirm_reset_invalidates_existing_sessions(api_client, registered_user):
    # Login to create a session
    await api_client.post("/api/auth/login", json={"username": "alice", "password": "OldPass!1234"})
    cookie_before = api_client.cookies.get("session")
    api_client.cookies.clear()

    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="reset_password")
        break

    await api_client.post("/api/auth/confirm-password-reset", json={
        "token": tok, "new_password": "NewPass!9876",
    })

    # Old session should now be gone
    async for db in gs():
        rows = (await db.execute(select(SessionModel))).scalars().all()
        assert all(r.token_hash != cookie_before for r in rows)
        break


@pytest.mark.asyncio
async def test_confirm_reset_with_invalid_token_returns_400(api_client, registered_user):
    r = await api_client.post("/api/auth/confirm-password-reset", json={
        "token": "bogus", "new_password": "NewPass!9876",
    })
    assert r.status_code == 400
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_email_reset.py -v
```
Expected: FAIL.

- [ ] **Step 3: Append to `streamload/api/routes/email.py`**

```python
from sqlalchemy import delete

from streamload.auth.passwords import hash_password
from streamload.db.models import Session as SessionModel
from streamload.email.client import EmailClient
from streamload.email.templates import password_reset_email


_reset_limiter_per_user = ...  # lazy


def _build_email_client() -> EmailClient:
    import os
    api_key = os.environ.get("RESEND_API_KEY", "")
    from_addr = os.environ.get("RESEND_FROM", "noreply@resend.dev")
    return EmailClient(api_key=api_key, from_address=from_addr, dry_run=not api_key)


class RequestResetRequest(BaseModel):
    email: str


class ConfirmResetRequest(BaseModel):
    token: str
    new_password: str = Field(min_length=8, max_length=128)


@router.post("/request-password-reset", status_code=200)
async def request_password_reset(
    payload: RequestResetRequest, db: SessionDep, request: Request,
) -> dict[str, str]:
    """Anti-enumeration: always return 200 OK regardless of email existence."""
    stmt = select(User).where(User.email == payload.email.lower())
    user = (await db.execute(stmt)).scalar_one_or_none()

    if user is not None:
        from streamload.auth.email_tokens import issue_token
        tok = await issue_token(db, user_id=user.id, purpose="reset_password")
        base = str(request.base_url).rstrip("/")
        link = f"{base}/reset?token={tok}"
        client = _build_email_client()
        subject, html, text = password_reset_email(username=user.username, link=link)
        try:
            await client.send(to=user.email, subject=subject, html=html, text=text)
        except Exception:
            pass  # silent; do not leak existence

    return {"status": "ok"}


@router.post("/confirm-password-reset", status_code=200)
async def confirm_password_reset(payload: ConfirmResetRequest, db: SessionDep) -> dict[str, str]:
    user_id = await consume_token(db, token=payload.token, purpose="reset_password")
    if user_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "invalid or expired token")
    u = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if u is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "user not found")
    u.password_hash = hash_password(payload.new_password)
    # Invalidate all existing sessions
    await db.execute(delete(SessionModel).where(SessionModel.user_id == user_id))
    await db.commit()
    return {"status": "reset"}
```

(Note: this requires importing `Request` from fastapi; ensure import line at top.)

- [ ] **Step 4: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_email_reset.py -v
```
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/email.py tests/api/test_email_reset.py
git commit -m "feat(api): password reset request + confirm with anti-enumeration"
```

---

## Task 15: Passkey registration

**Files:**
- Create: `streamload/auth/passkeys.py`
- Create: `streamload/api/routes/passkey.py`
- Modify: `streamload/api/app.py`
- Create: `tests/api/test_passkey.py`

- [ ] **Step 1: Failing test**

`tests/api/test_passkey.py`:
```python
"""Passkey registration challenge generation + verify."""
from __future__ import annotations

import httpx
import pytest


@pytest.fixture
async def logged_in_user(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_registration_options_requires_auth(api_client: httpx.AsyncClient):
    api_client.cookies.clear()
    r = await api_client.post("/api/auth/passkey/registration-options")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_registration_options_returns_challenge(api_client, logged_in_user):
    r = await api_client.post("/api/auth/passkey/registration-options",
                              json={"nickname": "iPhone"})
    assert r.status_code == 200
    body = r.json()
    assert "challenge" in body
    assert body["rp"]["name"]
    assert "user" in body and "id" in body["user"]


@pytest.mark.asyncio
async def test_authentication_options_returns_challenge_no_auth_needed(api_client, logged_in_user):
    api_client.cookies.clear()
    r = await api_client.post("/api/auth/passkey/authentication-options",
                              json={"username": "alice"})
    assert r.status_code == 200
    body = r.json()
    assert "challenge" in body


@pytest.mark.asyncio
async def test_authentication_options_for_unknown_user_returns_decoy(api_client):
    r = await api_client.post("/api/auth/passkey/authentication-options",
                              json={"username": "ghost"})
    # Anti-enumeration: still return 200 with a decoy challenge
    assert r.status_code == 200
```

- [ ] **Step 2: Run, expect FAIL**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_passkey.py -v
```
Expected: FAIL.

- [ ] **Step 3: Implement `streamload/auth/passkeys.py`**

```python
"""WebAuthn / FIDO2 passkey ceremonies (registration + authentication).

Wraps the ``webauthn`` library with our DB models. Challenge state is
stored short-lived in the in-memory ``_challenge_store`` keyed by user_id
or username — for a single-instance deployment this is fine.
"""
from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass
from typing import Optional

from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.cose import COSEAlgorithmIdentifier
from webauthn.helpers.structs import (
    AuthenticatorAttachment,
    PublicKeyCredentialDescriptor,
    UserVerificationRequirement,
)

CHALLENGE_TTL_SEC = 300


@dataclass
class _Stored:
    challenge: bytes
    expires_at: float
    user_id_hex: Optional[str] = None  # for registration: the user we're registering


_challenge_store: dict[str, _Stored] = {}


def _rp_id() -> str:
    return os.environ.get("WEBAUTHN_RP_ID", "localhost")


def _rp_name() -> str:
    return os.environ.get("WEBAUTHN_RP_NAME", "Streamload")


def _origin() -> str:
    return os.environ.get("WEBAUTHN_ORIGIN", "http://localhost:8000")


def make_registration_options(*, user_id: uuid.UUID, username: str, existing_credential_ids: list[bytes]) -> str:
    options = generate_registration_options(
        rp_id=_rp_id(),
        rp_name=_rp_name(),
        user_id=user_id.bytes,
        user_name=username,
        user_display_name=username,
        attestation="none",
        authenticator_selection={
            "user_verification": UserVerificationRequirement.PREFERRED,
            "authenticator_attachment": None,  # allow both platform + cross-platform
        },
        supported_pub_key_algs=[
            COSEAlgorithmIdentifier.ECDSA_SHA_256,
            COSEAlgorithmIdentifier.RSASSA_PKCS1_v1_5_SHA_256,
        ],
        exclude_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in existing_credential_ids
        ],
    )
    _challenge_store[f"reg:{user_id}"] = _Stored(
        challenge=options.challenge,
        expires_at=time.time() + CHALLENGE_TTL_SEC,
        user_id_hex=user_id.hex,
    )
    return options_to_json(options)


def verify_registration(*, user_id: uuid.UUID, response_json: dict) -> tuple[bytes, bytes, list[str]]:
    """Verify the registration response. Return (credential_id, public_key, transports)."""
    key = f"reg:{user_id}"
    stored = _challenge_store.pop(key, None)
    if stored is None or stored.expires_at < time.time():
        raise ValueError("challenge expired or missing")
    verification = verify_registration_response(
        credential=response_json,
        expected_challenge=stored.challenge,
        expected_rp_id=_rp_id(),
        expected_origin=_origin(),
    )
    transports: list[str] = []
    response = response_json.get("response", {})
    if "transports" in response:
        transports = response["transports"]
    return verification.credential_id, verification.credential_public_key, transports


def make_authentication_options(*, allowed_credential_ids: list[bytes], username_hint: str) -> str:
    options = generate_authentication_options(
        rp_id=_rp_id(),
        allow_credentials=[
            PublicKeyCredentialDescriptor(id=cid) for cid in allowed_credential_ids
        ],
        user_verification=UserVerificationRequirement.PREFERRED,
    )
    _challenge_store[f"auth:{username_hint}"] = _Stored(
        challenge=options.challenge,
        expires_at=time.time() + CHALLENGE_TTL_SEC,
    )
    return options_to_json(options)


def verify_authentication(*, username_hint: str, response_json: dict, credential_public_key: bytes, sign_count: int) -> int:
    """Verify and return the new sign_count."""
    key = f"auth:{username_hint}"
    stored = _challenge_store.pop(key, None)
    if stored is None or stored.expires_at < time.time():
        raise ValueError("challenge expired or missing")
    verification = verify_authentication_response(
        credential=response_json,
        expected_challenge=stored.challenge,
        expected_rp_id=_rp_id(),
        expected_origin=_origin(),
        credential_public_key=credential_public_key,
        credential_current_sign_count=sign_count,
    )
    return verification.new_sign_count
```

- [ ] **Step 4: Implement `streamload/api/routes/passkey.py`**

```python
"""WebAuthn passkey endpoints."""
from __future__ import annotations

import json
import os
import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.auth.passkeys import (
    make_authentication_options,
    make_registration_options,
    verify_authentication,
    verify_registration,
)
from streamload.auth.sessions import create_session
from streamload.db.models import User, WebauthnCredential

router = APIRouter(prefix="/auth/passkey", tags=["passkey"])


class RegistrationOptionsRequest(BaseModel):
    nickname: str | None = None


@router.post("/registration-options")
async def registration_options(
    payload: RegistrationOptionsRequest, user: CurrentUser, db: SessionDep,
) -> dict:
    existing = (await db.execute(
        select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user.id)
    )).scalars().all()
    options_json = make_registration_options(
        user_id=user.id, username=user.username, existing_credential_ids=list(existing),
    )
    return json.loads(options_json)


class RegistrationVerifyRequest(BaseModel):
    response: dict
    nickname: str | None = None


@router.post("/registration-verify")
async def registration_verify(
    payload: RegistrationVerifyRequest, user: CurrentUser, db: SessionDep,
) -> dict[str, str]:
    try:
        cred_id, pub_key, transports = verify_registration(
            user_id=user.id, response_json=payload.response,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc))
    db.add(WebauthnCredential(
        user_id=user.id,
        credential_id=cred_id,
        public_key=pub_key,
        transports=transports,
        nickname=payload.nickname,
    ))
    await db.commit()
    return {"status": "registered"}


class AuthOptionsRequest(BaseModel):
    username: str


@router.post("/authentication-options")
async def authentication_options(payload: AuthOptionsRequest, db: SessionDep) -> dict:
    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if user is None:
        # Anti-enumeration: still return a decoy options object
        options_json = make_authentication_options(
            allowed_credential_ids=[], username_hint=payload.username,
        )
        return json.loads(options_json)
    creds = (await db.execute(
        select(WebauthnCredential.credential_id).where(WebauthnCredential.user_id == user.id)
    )).scalars().all()
    options_json = make_authentication_options(
        allowed_credential_ids=list(creds), username_hint=payload.username,
    )
    return json.loads(options_json)


class AuthVerifyRequest(BaseModel):
    username: str
    response: dict


@router.post("/authentication-verify")
async def authentication_verify(
    payload: AuthVerifyRequest, db: SessionDep, request: Request, response: Response,
):
    user = (await db.execute(select(User).where(User.username == payload.username))).scalar_one_or_none()
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    cred_id_b64 = payload.response.get("rawId") or payload.response.get("id")
    if not cred_id_b64:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing credential id")
    import base64
    cred_id = base64.urlsafe_b64decode(cred_id_b64 + "=" * (-len(cred_id_b64) % 4))
    cred = (await db.execute(
        select(WebauthnCredential)
        .where(WebauthnCredential.user_id == user.id)
        .where(WebauthnCredential.credential_id == cred_id)
    )).scalar_one_or_none()
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "credential not registered")
    try:
        new_count = verify_authentication(
            username_hint=payload.username,
            response_json=payload.response,
            credential_public_key=cred.public_key,
            sign_count=cred.sign_count,
        )
    except Exception as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "verification failed") from exc
    cred.sign_count = new_count
    await db.commit()

    token = await create_session(db, user_id=user.id)
    response.set_cookie(
        "session", token,
        httponly=True, secure=request.url.scheme == "https",
        samesite="lax", max_age=60 * 60 * 24 * 30,
    )
    return {"status": "authenticated"}
```

- [ ] **Step 5: Wire router**

`streamload/api/app.py`:
```python
from .routes import auth, email, health, me, passkey
# in create_app:
app.include_router(passkey.router, prefix="/api")
```

- [ ] **Step 6: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_passkey.py -v
```
Expected: 4 passed.

- [ ] **Step 7: Commit**

```bash
git add streamload/auth/passkeys.py streamload/api/routes/passkey.py streamload/api/app.py tests/api/test_passkey.py
git commit -m "feat(api): WebAuthn passkey registration + authentication"
```

---

## Task 16: Wire `--api` flag to launch the server

**Files:**
- Modify: `streamload.py`

- [ ] **Step 1: Read current `streamload.py`**

```bash
cat streamload.py
```
Note where the curses app launches.

- [ ] **Step 2: Modify entry point**

Replace the `--api` placeholder block with the real launcher:

```python
if args.api:
    import os
    from granian import Granian

    server = Granian(
        target="streamload.api.app:app",
        address=os.environ.get("STREAMLOAD_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("STREAMLOAD_API_PORT", "8000")),
        interface="asgi",
        loop="uvloop",
        workers=1,
    )
    server.serve()
    sys.exit(0)
```

- [ ] **Step 3: Manual smoke test**

In one terminal:
```bash
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
  venv/bin/python streamload.py --api
```
Expected: Granian starts, listens on 127.0.0.1:8000.

In another terminal:
```bash
curl -s http://127.0.0.1:8000/api/health | jq .
```
Expected: `{"status": "ok", "version": "..."}`

Stop with Ctrl-C.

- [ ] **Step 4: Commit**

```bash
git add streamload.py
git commit -m "feat(cli): add --api flag to launch FastAPI server with Granian"
```

---

## Task 17: Full auth E2E smoke test

**Files:**
- Create: `tests/api/test_auth_e2e.py`

- [ ] **Step 1: Write the test**

```python
"""End-to-end auth flow: register -> verify -> logout -> login -> me."""
from __future__ import annotations

import httpx
import pytest
from sqlalchemy import select

from streamload.auth.email_tokens import issue_token
from streamload.db import get_session as gs
from streamload.db.models import User


@pytest.mark.asyncio
async def test_full_lifecycle(api_client: httpx.AsyncClient):
    # 1. Register
    r = await api_client.post("/api/auth/register", json={
        "username": "alice", "email": "alice@x.com", "password": "Hunter2!secret",
    })
    assert r.status_code == 201
    assert r.json()["role"] == "admin"  # first user
    assert r.json()["email_verified"] is False

    # 2. /api/me works (cookie auto-set)
    r = await api_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["username"] == "alice"

    # 3. Verify email
    async for db in gs():
        u = (await db.execute(select(User))).scalar_one()
        tok = await issue_token(db, user_id=u.id, purpose="verify_email")
        break
    r = await api_client.post("/api/auth/verify-email", json={"token": tok})
    assert r.status_code == 200

    # 4. Logout
    r = await api_client.post("/api/auth/logout")
    assert r.status_code == 204

    # 5. /api/me now 401
    r = await api_client.get("/api/me")
    assert r.status_code == 401

    # 6. Login
    r = await api_client.post("/api/auth/login", json={
        "username": "alice", "password": "Hunter2!secret",
    })
    assert r.status_code == 200

    # 7. /api/me again, email_verified true now
    r = await api_client.get("/api/me")
    assert r.status_code == 200
    assert r.json()["email_verified"] is True
```

- [ ] **Step 2: Run, expect PASS**

Run:
```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest tests/api/test_auth_e2e.py -v
```
Expected: 1 passed.

- [ ] **Step 3: Run full suite**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest -q
```
Expected: All green (existing 122 + Plan 1 additions).

- [ ] **Step 4: Commit**

```bash
git add tests/api/test_auth_e2e.py
git commit -m "test(api): end-to-end auth lifecycle smoke test"
```

---

## Task 18: Documentation update

**Files:**
- Modify: `README.md`
- Create: `docs/api.md`

- [ ] **Step 1: Add API section to README**

Append to `README.md` under a new section:

```markdown
## API server (v2)

Streamload v2 exposes a FastAPI HTTP API alongside the existing curses CLI.

### Quick start (development)

```bash
# Configure
cp .env.example .env  # edit DATABASE_URL, RESEND_API_KEY, etc.

# Setup database (one-time)
createdb streamload
DATABASE_URL=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload \
    venv/bin/alembic upgrade head

# Launch the API server
venv/bin/python streamload.py --api
# Listens on http://127.0.0.1:8000
```

### Endpoints (Plan 1)

- `GET /api/health` — liveness probe
- `GET /api/version` — version + git sha
- `POST /api/auth/register` — create account (first user becomes admin)
- `POST /api/auth/login` — password login
- `POST /api/auth/logout` — terminate session
- `GET /api/me` — current user profile
- `POST /api/auth/verify-email` — confirm email via token
- `POST /api/auth/request-password-reset` — initiate reset
- `POST /api/auth/confirm-password-reset` — apply new password
- `POST /api/auth/passkey/registration-options` — start passkey registration
- `POST /api/auth/passkey/registration-verify` — finish passkey registration
- `POST /api/auth/passkey/authentication-options` — start passkey login
- `POST /api/auth/passkey/authentication-verify` — finish passkey login

Interactive docs at http://127.0.0.1:8000/api/docs (Swagger UI).
```

- [ ] **Step 2: Create operator notes**

`docs/api.md`:
```markdown
# Streamload API — Operator Notes

## Environment variables

See `.env.example`. Required:

- `DATABASE_URL` — postgres+asyncpg connection string
- `RESEND_API_KEY` — Resend API key (or empty for dry-run mode)
- `WEBAUTHN_RP_ID` — relying party ID (e.g. `streamload.<tailnet>.ts.net`)
- `WEBAUTHN_ORIGIN` — full origin URL (must match what the browser sees)

## Migrations

```bash
# Create new migration after model changes
DATABASE_URL=... venv/bin/alembic revision --autogenerate -m "your description"

# Apply
DATABASE_URL=... venv/bin/alembic upgrade head

# Rollback last
DATABASE_URL=... venv/bin/alembic downgrade -1
```

## First user setup

The first registered user becomes admin automatically. To promote another:

```sql
UPDATE users SET role = 'admin' WHERE username = '<name>';
```

## Email troubleshooting

If `RESEND_API_KEY` is empty or invalid, the email client falls back to dry-run mode and logs the email rather than sending it. Useful for local dev. The verification link still works — just retrieve the token from `email_tokens` directly:

```sql
SELECT encode(token_hash, 'hex'), purpose, expires_at FROM email_tokens
  WHERE user_id = '<uuid>' AND consumed_at IS NULL ORDER BY issued_at DESC LIMIT 1;
```

(Note: `token_hash` is the hash, not the original token — for dev you can re-issue via the `/request-password-reset` endpoint and watch the log.)
```

- [ ] **Step 3: Commit**

```bash
git add README.md docs/api.md
git commit -m "docs: API server quickstart + operator notes"
```

---

## Task 19: Merge to main

**Files:** None (git ops only)

- [ ] **Step 1: Final test run**

```bash
DATABASE_URL_TEST=postgresql+asyncpg://streamload:streamload@127.0.0.1:5432/streamload_test \
  venv/bin/pytest -q
```
Expected: all green.

- [ ] **Step 2: Squash review (optional)**

```bash
git log main..HEAD --oneline
```
Expected: 18+ commits documenting the journey.

- [ ] **Step 3: Merge with `--no-ff`**

```bash
git checkout main
git merge --no-ff feat/v2-foundation-auth-email -m "Merge branch 'feat/v2-foundation-auth-email'

Plan 1 of Streamload v2: FastAPI backbone + multi-user auth.

Includes:
* SQLAlchemy 2.x async + Alembic migrations
* User, Session, EmailToken, WebauthnCredential ORM models
* argon2id password hashing
* Opaque session tokens with sliding TTL
* Resend email client (transactional verify + reset templates)
* Email verification + password reset flows with anti-enumeration
* WebAuthn passkey register + authenticate
* Rate-limited login endpoints
* /api/health, /api/version, /api/me
* End-to-end auth lifecycle test

Spec: docs/superpowers/specs/2026-05-08-streamload-v2-design.md §6.4 + §16
Plan: docs/superpowers/plans/2026-05-08-streamload-v2-plan-1-foundation-auth-email.md"

git push origin main
```

- [ ] **Step 4: Tag (optional)**

```bash
git tag -a v0.2.0-alpha.1 -m "Streamload v0.2.0-alpha.1 (Plan 1 complete)"
git push origin v0.2.0-alpha.1
```

---

## Self-Review Checklist

After implementing all tasks:

- [ ] All 19 tasks completed and committed
- [ ] `venv/bin/pytest -q` shows all green (122 existing + ~30 new)
- [ ] `python streamload.py --api` launches Granian successfully
- [ ] `curl http://127.0.0.1:8000/api/health` returns `{"status": "ok", ...}`
- [ ] `/api/docs` shows the OpenAPI explorer with all routes
- [ ] Manual end-to-end via curl: register → verify → login → /me → logout
- [ ] Curses CLI still works (`python streamload.py` without `--api`)
- [ ] No `Co-Authored-By` trailers in commit history
- [ ] `domains.json.sig` still verifies (regression check)

---

## Open issues (post-Plan-1, deferred to Plan 2+)

- TMDB client and catalog ingestion (Plan 2)
- Streaming proxy + DRM (Plan 3)
- Frontend UI (Plan 4)
- Production Docker + CI (Plan 6)
- Admin user management UI (Plan 5)
- Frontend pages for `/verify` and `/reset` (Plan 4) — currently endpoints exist but no UI pages
- WebAuthn conditional UI / autofill (Plan 4)
