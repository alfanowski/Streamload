# v3 Backend Reduction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Strip the v0.2.x backend down to its v3 shape — pure auth + TMDB metadata mirror + user-state sync + telemetry — by deleting all scraping/streaming/CLI code, dropping radioactive tables, adding new tables for settings/history/events, and wiring three new endpoints. Ship as `v0.3.0`.

**Architecture:** Single Alembic migration adds and removes schema in one transaction. The Python codebase loses six top-level packages and three route modules. Three new route modules (`settings.py` rewrite, `next_up.py`, `events.py`) come online. Existing routes that emitted scraping-coupled fields are surgically simplified. Backend version bumps to 0.3.0; the v2 web frontend will start receiving 404 from `/api/play/*` and `/stream/*`, which is the deliberate signal to move to v3.

**Tech Stack:** Python 3.14, FastAPI, SQLAlchemy 2.x async + asyncpg, Alembic, pytest + pytest-asyncio, Postgres 16.

---

## Source spec

This plan implements **Sub-plan #1** from `docs/superpowers/specs/2026-05-09-streamload-v3-design.md` §17.

## File structure

### Files DELETED (entire directories or single files)

| Path | Reason |
|---|---|
| `streamload/services/` (whole dir) | All upstream scraping plugins. Move to private repo per design invariant 1. |
| `streamload/streaming/` (whole dir) | HLS proxy, segment cache, m3u8 rewriter, DRM. Move to client. |
| `streamload/utils/domain_resolver/` (whole dir) | Domain rotation for upstream services. Client-only concern. |
| `streamload/cli/` (whole dir) | v1 download tool, depends on services and core. v3 supersedes it. |
| `streamload/core/` (whole dir) | v1 downloader internals (DRM, manifest parsing, post-process). |
| `streamload/models/` (whole dir) | `MediaEntry`, `Episode`, `Season` dataclasses used by services. Dead with services. |
| `streamload/api/routes/play.py` | Playback session creation. Lives in client. |
| `streamload/api/routes/stream.py` | HLS proxy. Lives in client. |
| `tests/services/` (whole dir) | Tests for deleted services. |
| `tests/streaming/` (whole dir) | Tests for deleted streaming module. |
| `tests/test_cli_domains.py` | CLI test, depends on cli. |
| `tests/test_cli_resolver_wiring.py` | Same. |
| `tests/test_config_services.py` | Service config test. |
| `tests/test_sc_extractor_fhd.py` | StreamingCommunity extractor test. |
| `tests/test_service_base_failure.py` | services.base test. |
| `tests/test_service_base_resolver.py` | Same. |
| `tests/test_sign_domains_tool.py` | Domain signing tool test. |
| `tests/test_vixcloud_parser.py` | VixCloud parser test. |
| `tests/api/test_play.py` | Tests deleted route. |
| `tests/api/test_stream.py` | Tests deleted route. |
| `tests/api/test_stream_e2e.py` | E2E test for deleted routes. |
| `tests/api/test_admin_refresh.py` | Tests deleted admin refresh route. |
| `scripts/seed_catalog.py` | Imports services for reverse-lookup. v3 client handles this. |

### Files CREATED

| Path | Responsibility |
|---|---|
| `migrations/versions/0008_v3_remodel.py` | Drop catalog_sources + last_source col; create user_settings, watch_history, search_history, events. |
| `streamload/api/routes/next_up.py` | `GET /next-up/{tmdb_id}?season=&episode=` returning the next episode (same season then next season). |
| `streamload/api/routes/events.py` | `POST /events` accepting batch telemetry (closed enum validation). |
| `tests/api/test_next_up.py` | Tests for next-up endpoint. |
| `tests/api/test_events.py` | Tests for events endpoint. |
| `tests/db/test_v3_models.py` | Tests for new model classes (column shapes, PK shapes). |

### Files MODIFIED

| Path | Change |
|---|---|
| `streamload/db/models.py` | Drop `CatalogSource` class. Drop `last_source` from `WatchProgress`. Add `UserSettings`, `WatchHistory`, `SearchHistory`, `Event` classes. |
| `streamload/api/app.py` | Drop import + include of `play`, `stream`, `catalog.admin_router`. Add include of `next_up`, `events`. Drop the `from streamload.api.routes.stream import shutdown_http` call in lifespan. |
| `streamload/api/routes/catalog.py` | Lazy-ingest TMDB-only (no `services` arg). Strip CatalogSource imports. Always return `sources=[]`. Drop the episode backfill that touches CatalogSource. Drop the entire `_refresh_one` + `admin_router` block (they trigger scraping). |
| `streamload/api/routes/admin.py` | Drop the `total_sources` KPI. Drop `/admin/health/domains` endpoint. |
| `streamload/api/routes/progress.py` | Drop `source` from `PostProgressRequest`, drop `last_source` from upsert. On `completed=True` flip, insert into `watch_history`. Emit `play.complete` telemetry. |
| `streamload/api/routes/favorites.py` | Emit `favorite.add` / `favorite.remove` telemetry. |
| `streamload/api/routes/watchlist.py` | Emit `watchlist.add` / `watchlist.remove` telemetry. |
| `streamload/api/routes/auth.py` | Emit `auth.login_success` / `auth.login_failed` / `auth.logout` telemetry. |
| `streamload/api/routes/passkey.py` | Emit `auth.passkey_register` telemetry on register/complete. |
| `streamload/api/routes/search.py` | Insert into `search_history` (text + sha256 hash). Emit `search.run` telemetry. |
| `streamload/api/routes/settings.py` | Replace stub with real DB-backed UserSettings GET/PUT. |
| `streamload/catalog/ingest.py` | Drop `_resolve_sources_for_item`. Drop `services` parameter from `ingest_collection` and `ingest_single_title`. Drop `CatalogSource` import. |
| `streamload/catalog/worker.py` | Drop `_load_services` + `services` arg; refresh_due_collections no longer takes services. |
| `streamload.py` | Drop CLI fallback (the entire non-`--api` branch). Always run API. |
| `streamload/version.py` | Bump to `0.3.0`. |
| `streamload/utils/__init__.py` | Drop any `domain_resolver` re-exports if present. |
| `tests/api/test_admin.py` | Drop assertions about `total_sources` / `domains` endpoint. |
| `tests/api/test_catalog.py` | Drop CatalogSource assertions; assert `sources=[]` always. |
| `tests/api/test_progress.py` | Drop `source` from payload; add test for `watch_history` insertion on completion. |
| `tests/api/test_favorites.py` | Add assertions for telemetry event row. |
| `tests/api/test_watchlist.py` | Add assertions for telemetry event row. |
| `tests/api/test_settings.py` | Replace stub assertions with real GET/PUT round-trip + persistence. |
| `tests/db/test_catalog_models.py` | Drop `test_catalog_source_pk`. |
| `tests/conftest.py` | Drop `catalog_sources` from the truncate list (table no longer exists). |
| `tests/api/conftest.py` | Same. |

---

## Phase A — Schema migration

### Task 1: Migration up half — drop the radioactive table + column

**Files:**
- Create: `migrations/versions/0008_v3_remodel.py`

- [ ] **Step 1: Create migration file with metadata + upgrade-drop section**

```python
"""v3 remodel: drop scraping schema, add user_settings/history/events

Revision ID: d2c3e4f50004
Revises: f0a1b2c30003
Create Date: 2026-05-09 21:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB, INET


revision: str = "d2c3e4f50004"
down_revision: Union[str, Sequence[str], None] = "f0a1b2c30003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Drop catalog_sources entirely (CASCADE removes its FK from itself).
    op.drop_table("catalog_sources")

    # ── 2. Drop last_source column from watch_progress (radioactive).
    op.drop_column("watch_progress", "last_source")
```

- [ ] **Step 2: Run migration up against dev DB, verify drops happened**

```bash
cd /Users/alfanowski/Desktop/Projects/Streamload
set -a; source .env; set +a
venv/bin/alembic upgrade head
```

Expected output: `Running upgrade f0a1b2c30003 -> d2c3e4f50004, v3 remodel: drop scraping schema, add user_settings/history/events`.

Verify:

```bash
venv/bin/python -c "
import asyncio, os, asyncpg
async def main():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    print('catalog_sources exists:', await conn.fetchval(\"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name='catalog_sources')\"))
    print('last_source col exists:', await conn.fetchval(\"SELECT EXISTS(SELECT 1 FROM information_schema.columns WHERE table_name='watch_progress' AND column_name='last_source')\"))
    await conn.close()
asyncio.run(main())
"
```

Expected:

```
catalog_sources exists: False
last_source col exists: False
```

- [ ] **Step 3: Commit**

```bash
git add migrations/versions/0008_v3_remodel.py
git commit -m "migration(0008): drop catalog_sources + watch_progress.last_source"
```

---

### Task 2: Migration up half — add user_settings + watch_history + search_history + events

**Files:**
- Modify: `migrations/versions/0008_v3_remodel.py`

- [ ] **Step 1: Append CREATE TABLE blocks to upgrade()**

Append below the drop_column line in `upgrade()`:

```python
    # ── 3. user_settings: one row per user, last-write-wins via updated_at.
    op.create_table(
        "user_settings",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("audio_pref_lang", sa.Text(), nullable=False, server_default="ita"),
        sa.Column("subs_pref_lang", sa.Text(), nullable=False, server_default="ita"),
        sa.Column("quality_cap_height", sa.Integer(), nullable=True),
        sa.Column("autoplay_next_episode", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("skip_intro", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("theme", sa.Text(), nullable=False, server_default="auto"),
        sa.Column("locale", sa.Text(), nullable=False, server_default="it-IT"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("user_id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.CheckConstraint("theme IN ('auto', 'light', 'dark')", name="ck_user_settings_theme"),
    )

    # ── 4. watch_history: append-only log of completed episodes/movies.
    op.create_table(
        "watch_history",
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("season_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("episode_number", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("user_id", "tmdb_id", "media_type", "season_number", "episode_number", "completed_at"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["tmdb_id", "media_type"],
            ["catalog_items.tmdb_id", "catalog_items.media_type"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_watch_history_user_completed", "watch_history", ["user_id", "completed_at"])

    # ── 5. search_history: per-user query log, plain text + sha256 for analytics.
    op.create_table(
        "search_history",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_hash", sa.CHAR(64), nullable=False),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_search_history_user_executed", "search_history", ["user_id", "executed_at"])

    # ── 6. events: telemetry sink (level B per spec §5.4).
    op.create_table(
        "events",
        sa.Column("id", sa.BigInteger(), nullable=False, autoincrement=True),
        sa.Column("user_id", sa.dialects.postgresql.UUID(as_uuid=True), nullable=True),  # nullable for pre-auth events
        sa.Column("event_type", sa.Text(), nullable=False),
        sa.Column("payload", JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("ip", INET(), nullable=True),
        sa.Column("user_agent", sa.Text(), nullable=True),
        sa.Column("app_version", sa.Text(), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_events_user_occurred", "events", ["user_id", "occurred_at"])
    op.create_index("ix_events_type_occurred", "events", ["event_type", "occurred_at"])
```

- [ ] **Step 2: Run upgrade — already-upgraded DBs are rolled back to f0a1b2c30003 first**

```bash
venv/bin/alembic downgrade f0a1b2c30003
venv/bin/alembic upgrade head
```

Expected: both runs succeed without error.

- [ ] **Step 3: Verify all four new tables exist**

```bash
venv/bin/python -c "
import asyncio, os, asyncpg
async def main():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    for t in ('user_settings', 'watch_history', 'search_history', 'events'):
        print(t, '→', await conn.fetchval(\"SELECT EXISTS(SELECT 1 FROM information_schema.tables WHERE table_name=\\$1)\", t))
    await conn.close()
asyncio.run(main())
"
```

Expected: all four print `True`.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/0008_v3_remodel.py
git commit -m "migration(0008): add user_settings, watch_history, search_history, events"
```

---

### Task 3: Migration down half (reverse the four creates and the two drops)

**Files:**
- Modify: `migrations/versions/0008_v3_remodel.py`

- [ ] **Step 1: Append `downgrade()`**

```python
def downgrade() -> None:
    op.drop_index("ix_events_type_occurred", table_name="events")
    op.drop_index("ix_events_user_occurred", table_name="events")
    op.drop_table("events")

    op.drop_index("ix_search_history_user_executed", table_name="search_history")
    op.drop_table("search_history")

    op.drop_index("ix_watch_history_user_completed", table_name="watch_history")
    op.drop_table("watch_history")

    op.drop_table("user_settings")

    op.add_column(
        "watch_progress",
        sa.Column("last_source", sa.Text(), nullable=True),
    )

    op.create_table(
        "catalog_sources",
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.Text(), nullable=False),
        sa.Column("service_short_name", sa.Text(), nullable=False),
        sa.Column("service_url", sa.Text(), nullable=False),
        sa.Column("service_media_id", sa.Text(), nullable=False),
        sa.Column("quality_max_height", sa.Integer(), nullable=True),
        sa.Column("languages_audio", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("languages_subs", sa.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("success_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failure_count", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("tmdb_id", "media_type", "service_short_name"),
        sa.ForeignKeyConstraint(
            ["tmdb_id", "media_type"],
            ["catalog_items.tmdb_id", "catalog_items.media_type"],
            ondelete="CASCADE",
        ),
    )
    op.create_index("ix_catalog_sources_service_short_name", "catalog_sources", ["service_short_name"])
```

- [ ] **Step 2: Round-trip test — downgrade then re-upgrade**

```bash
venv/bin/alembic downgrade f0a1b2c30003
venv/bin/alembic upgrade head
```

Expected: both succeed; `catalog_sources` reappears after downgrade then disappears after upgrade.

- [ ] **Step 3: Apply to test DB too**

```bash
DATABASE_URL=$DATABASE_URL_TEST venv/bin/alembic upgrade head
```

Expected: succeeds.

- [ ] **Step 4: Commit**

```bash
git add migrations/versions/0008_v3_remodel.py
git commit -m "migration(0008): downgrade reverses every up-step cleanly"
```

---

## Phase B — Update ORM models

### Task 4: Drop `CatalogSource` and `last_source` from models.py

**Files:**
- Modify: `streamload/db/models.py`

- [ ] **Step 1: Update the failing test FIRST**

Edit `tests/db/test_catalog_models.py` to remove the test that asserts on the deleted PK:

```python
# Delete this entire function:
def test_catalog_source_pk():
    pk = {c.name for c in CatalogSource.__table__.primary_key.columns}
    assert pk == {"tmdb_id", "media_type", "service_short_name"}
```

Also remove `CatalogSource` from the import at the top:

```python
# Before
from streamload.db.models import (
    CatalogItem, CatalogSource, Collection, CollectionItem, TvEpisode,
)

# After
from streamload.db.models import (
    CatalogItem, Collection, CollectionItem, TvEpisode,
)
```

- [ ] **Step 2: Run the suite, confirm only that one test is gone (not failing)**

```bash
venv/bin/python -m pytest tests/db/test_catalog_models.py -v
```

Expected: 4 tests pass (item_columns, item_pk, collection_columns, collection_item_pk, tv_episode_pk — minus the deleted one). No failures.

- [ ] **Step 3: Delete the `CatalogSource` class from `streamload/db/models.py`**

Find the class definition (currently at ~line 200). Delete the entire `class CatalogSource(Base):` block AND its preceding blank lines.

Also remove the `sources` relationship from `CatalogItem`:

```python
# Before (in CatalogItem)
    sources: Mapped[list["CatalogSource"]] = relationship(
        back_populates="item", cascade="all, delete-orphan",
    )

# After
    # (no sources relationship — that's a client-only concern in v3)
```

- [ ] **Step 4: Drop `last_source` from `WatchProgress`**

In `class WatchProgress(Base)`, remove this line:

```python
    last_source: Mapped[Optional[str]] = mapped_column(Text)
```

- [ ] **Step 5: Run model tests**

```bash
venv/bin/python -m pytest tests/db/ -v
```

Expected: all model tests pass; no import errors.

- [ ] **Step 6: Commit**

```bash
git add streamload/db/models.py tests/db/test_catalog_models.py
git commit -m "refactor(models): drop CatalogSource and watch_progress.last_source"
```

---

### Task 5: Add the four new model classes

**Files:**
- Modify: `streamload/db/models.py`
- Create: `tests/db/test_v3_models.py`

- [ ] **Step 1: Write failing tests for the new model shapes**

Create `tests/db/test_v3_models.py`:

```python
from streamload.db.models import UserSettings, WatchHistory, SearchHistory, Event


def test_user_settings_pk():
    pk = {c.name for c in UserSettings.__table__.primary_key.columns}
    assert pk == {"user_id"}


def test_user_settings_columns():
    cols = {c.name for c in UserSettings.__table__.columns}
    assert cols >= {"user_id", "audio_pref_lang", "subs_pref_lang",
                    "quality_cap_height", "autoplay_next_episode", "skip_intro",
                    "theme", "locale", "updated_at"}


def test_watch_history_pk():
    pk = {c.name for c in WatchHistory.__table__.primary_key.columns}
    assert pk == {"user_id", "tmdb_id", "media_type", "season_number",
                  "episode_number", "completed_at"}


def test_search_history_pk():
    pk = {c.name for c in SearchHistory.__table__.primary_key.columns}
    assert pk == {"id"}


def test_search_history_has_query_hash_column():
    cols = {c.name for c in SearchHistory.__table__.columns}
    assert "query_hash" in cols
    assert "query_text" in cols


def test_event_pk():
    pk = {c.name for c in Event.__table__.primary_key.columns}
    assert pk == {"id"}


def test_event_payload_is_jsonb():
    from sqlalchemy.dialects.postgresql import JSONB
    payload_col = Event.__table__.c.payload
    assert isinstance(payload_col.type, JSONB)
```

- [ ] **Step 2: Run — expect ImportError**

```bash
venv/bin/python -m pytest tests/db/test_v3_models.py -v
```

Expected: ImportError on `UserSettings, WatchHistory, SearchHistory, Event`.

- [ ] **Step 3: Add the four classes to `streamload/db/models.py`**

Append at the end of the file:

```python
class UserSettings(Base):
    __tablename__ = "user_settings"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    audio_pref_lang: Mapped[str] = mapped_column(Text, nullable=False, server_default="ita")
    subs_pref_lang: Mapped[str] = mapped_column(Text, nullable=False, server_default="ita")
    quality_cap_height: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    autoplay_next_episode: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    skip_intro: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    theme: Mapped[str] = mapped_column(Text, nullable=False, server_default="auto")
    locale: Mapped[str] = mapped_column(Text, nullable=False, server_default="it-IT")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )

    __table_args__ = (
        CheckConstraint("theme IN ('auto', 'light', 'dark')", name="ck_user_settings_theme"),
    )


class WatchHistory(Base):
    __tablename__ = "watch_history"

    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), primary_key=True,
    )
    tmdb_id: Mapped[int] = mapped_column(Integer, primary_key=True)
    media_type: Mapped[str] = mapped_column(Text, primary_key=True)
    season_number: Mapped[int] = mapped_column(Integer, primary_key=True, default=0, server_default="0")
    episode_number: Mapped[int] = mapped_column(Integer, primary_key=True, default=0, server_default="0")
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), primary_key=True, server_default=func.now(),
    )

    __table_args__ = (
        ForeignKeyConstraint(
            ["tmdb_id", "media_type"],
            ["catalog_items.tmdb_id", "catalog_items.media_type"],
            ondelete="CASCADE",
        ),
    )


class SearchHistory(Base):
    __tablename__ = "search_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False,
    )
    query_text: Mapped[str] = mapped_column(Text, nullable=False)
    query_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    executed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[Optional[uuid.UUID]] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb"),
    )
    ip: Mapped[Optional[str]] = mapped_column(INET, nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    app_version: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(),
    )
```

If `text` is not yet imported, add to the SQLAlchemy import block at the top:

```python
from sqlalchemy import (
    ...,
    text,
)
```

- [ ] **Step 4: Run tests, expect green**

```bash
venv/bin/python -m pytest tests/db/test_v3_models.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 5: Commit**

```bash
git add streamload/db/models.py tests/db/test_v3_models.py
git commit -m "feat(models): add UserSettings, WatchHistory, SearchHistory, Event"
```

---

## Phase C — Delete dead modules

These tasks delete entire directories. They're irreversible from a working-copy perspective (git keeps them), so do them as separate commits to make rollback granular.

### Task 6: Delete `streamload/api/routes/play.py` and `streamload/api/routes/stream.py` + their tests

**Files:**
- Delete: `streamload/api/routes/play.py`
- Delete: `streamload/api/routes/stream.py`
- Delete: `tests/api/test_play.py`
- Delete: `tests/api/test_stream.py`
- Delete: `tests/api/test_stream_e2e.py`
- Modify: `streamload/api/app.py`

- [ ] **Step 1: Delete the files**

```bash
git rm streamload/api/routes/play.py streamload/api/routes/stream.py
git rm tests/api/test_play.py tests/api/test_stream.py tests/api/test_stream_e2e.py
```

- [ ] **Step 2: Update `streamload/api/app.py`**

Open and edit:

```python
# Before — line ~12
from .routes import admin, auth, catalog, collections, email, episodes, favorites, health, intro, library, me, passkey, play, progress, search, settings, stream, watchlist
from .routes.catalog import admin_router as catalog_admin_router

# After
from .routes import admin, auth, catalog, collections, email, episodes, favorites, health, intro, library, me, passkey, progress, search, settings, watchlist
```

In the `lifespan()` function, remove this block (currently in the `finally`):

```python
        # Close the streaming HTTP singleton if it was created.
        from streamload.api.routes.stream import shutdown_http
        await shutdown_http()
```

In `create_app()`, remove these two lines:

```python
    app.include_router(catalog_admin_router, prefix="/api")
    ...
    app.include_router(play.router, prefix="/api")
    app.include_router(stream.router)  # mounted at /stream (no /api/ prefix)
```

- [ ] **Step 3: Smoke-test app boot**

```bash
venv/bin/python -c "from streamload.api.app import create_app; print('routes:', len(create_app().routes))"
```

Expected: prints a number; no ImportError. The number will be lower than before (~46 instead of 49).

- [ ] **Step 4: Commit**

```bash
git add streamload/api/app.py
git commit -m "refactor(api): drop /api/play and /stream routes — moved to v3 client"
```

---

### Task 7: Delete `streamload/services/` and its tests

**Files:**
- Delete: `streamload/services/` (whole dir)
- Delete: `tests/services/` (whole dir)
- Delete: `tests/test_service_base_failure.py`
- Delete: `tests/test_service_base_resolver.py`
- Delete: `tests/test_config_services.py`
- Delete: `tests/test_sc_extractor_fhd.py`
- Delete: `tests/test_vixcloud_parser.py`

- [ ] **Step 1: Verify nothing else imports from services (besides files we'll also delete)**

```bash
grep -rln "from streamload.services\|import streamload.services" streamload/ \
  | grep -v -E '^streamload/(services|cli|streaming|api/routes/(play|stream|catalog))\.py$|^streamload/(services|cli|streaming)/' \
  | head
```

Expected: only `streamload/api/routes/catalog.py` shows up (we fix it in Task 12). Anything else here is a hidden dependency we missed.

- [ ] **Step 2: Delete the directory and tests**

```bash
git rm -r streamload/services/
git rm -r tests/services/
git rm tests/test_service_base_failure.py tests/test_service_base_resolver.py \
       tests/test_config_services.py tests/test_sc_extractor_fhd.py \
       tests/test_vixcloud_parser.py
```

- [ ] **Step 3: Confirm import surface still loads (will fail until Task 12)**

```bash
venv/bin/python -c "from streamload.api.app import create_app; create_app()" 2>&1 | tail -3
```

Expected: ImportError pointing at `streamload.api.routes.catalog` (still imports services). That's expected — Task 12 fixes it.

- [ ] **Step 4: Commit (without expecting tests to run cleanly yet)**

```bash
git commit -m "refactor: delete streamload/services/ and its tests — v3 plugins live elsewhere"
```

---

### Task 8: Delete `streamload/streaming/` and its tests

**Files:**
- Delete: `streamload/streaming/` (whole dir)
- Delete: `tests/streaming/` (whole dir)

- [ ] **Step 1: Verify only deleted files import from streaming**

```bash
grep -rln "from streamload.streaming\|import streamload.streaming" streamload/ \
  | grep -v -E '^streamload/streaming/' | head
```

Expected: empty output (we already deleted play.py and stream.py in Task 6).

- [ ] **Step 2: Delete**

```bash
git rm -r streamload/streaming/
git rm -r tests/streaming/
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: delete streamload/streaming/ — HLS proxy lives in v3 client"
```

---

### Task 9: Delete `streamload/utils/domain_resolver/` and its tests

**Files:**
- Delete: `streamload/utils/domain_resolver/` (whole dir)
- Delete: `tests/test_sign_domains_tool.py`

- [ ] **Step 1: Find remaining references**

```bash
grep -rln "domain_resolver" streamload/ tests/ | grep -v __pycache__ | head
```

Expected output may include `streamload/cli/` and `streamload/api/routes/admin.py` and possibly tests files. Both will be cleaned up in later tasks. The deletion is safe to do now because Python won't try to import what nobody requires (after we delete cli too).

- [ ] **Step 2: Delete the directory and the related test**

```bash
git rm -r streamload/utils/domain_resolver/
git rm tests/test_sign_domains_tool.py
```

- [ ] **Step 3: Verify no `__init__.py` re-exports it**

```bash
grep -n "domain_resolver" streamload/utils/__init__.py 2>/dev/null
```

If anything is found, edit to remove the offending lines. If nothing is found, skip.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "refactor: delete streamload/utils/domain_resolver/ — client-side concern"
```

---

### Task 10: Delete `streamload/cli/`, `streamload/core/`, `streamload/models/`

**Files:**
- Delete: `streamload/cli/` (whole dir)
- Delete: `streamload/core/` (whole dir)
- Delete: `streamload/models/` (whole dir)
- Delete: `tests/test_cli_domains.py`
- Delete: `tests/test_cli_resolver_wiring.py`

- [ ] **Step 1: Confirm nothing in `streamload/api/`, `streamload/auth/`, `streamload/catalog/`, `streamload/db/`, `streamload/email/` imports from these**

```bash
grep -rln "from streamload.cli\|from streamload.core\|from streamload.models" \
  streamload/api/ streamload/auth/ streamload/catalog/ streamload/db/ streamload/email/ \
  2>&1 | head
```

Expected: empty output (Task 12 will fix the one in catalog.py — but `from streamload.models import ...` should not be there yet because catalog.py uses TmdbItem from `streamload.catalog.tmdb`, not `streamload.models`).

- [ ] **Step 2: Delete**

```bash
git rm -r streamload/cli/ streamload/core/ streamload/models/
git rm tests/test_cli_domains.py tests/test_cli_resolver_wiring.py
```

- [ ] **Step 3: Commit**

```bash
git commit -m "refactor: delete streamload/cli, core, models — v1 download tool retired in v3"
```

---

### Task 11: Update `streamload.py` launcher to drop CLI mode

**Files:**
- Modify: `streamload.py`

- [ ] **Step 1: Read current state**

```bash
cat streamload.py
```

Expected: shows the `_load_dotenv` helper + an `if args.api:` block + a fallback that `from streamload.cli.app import StreamloadApp; app.run()`.

- [ ] **Step 2: Replace the file with API-only launcher**

```python
#!/usr/bin/env python3
"""Streamload backend launcher (v3 — API only).

The v1 CLI mode was retired in v3; the desktop client supersedes it.
"""

import argparse
import os
import sys
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from a sibling `.env` file into os.environ.

    Existing env vars take precedence (so a shell export overrides .env).
    Quiet no-op if the file is missing.
    """
    env_path = Path(__file__).resolve().parent / ".env"
    if not env_path.is_file():
        return
    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def main():
    if sys.version_info < (3, 11):
        print(
            f"Streamload requires Python 3.11+. You have "
            f"{sys.version_info.major}.{sys.version_info.minor}"
        )
        sys.exit(1)

    parser = argparse.ArgumentParser(description="Streamload v3 backend")
    parser.add_argument("--api", action="store_true", help="Start the API server (default)")
    args, _ = parser.parse_known_args()

    # API is the only supported mode in v3. The flag is preserved for
    # backwards compatibility with existing systemd/docker invocations.
    _load_dotenv()
    from granian import Granian

    server = Granian(
        target="streamload.api.app:app",
        address=os.environ.get("STREAMLOAD_API_HOST", "127.0.0.1"),
        port=int(os.environ.get("STREAMLOAD_API_PORT", "8000")),
        interface="asgi",
        loop="auto",
        workers=1,
    )
    server.serve()


if __name__ == "__main__":
    main()
```

- [ ] **Step 3: Smoke-test the launcher (5-second start, then kill)**

```bash
pkill -9 -f granian 2>/dev/null
sleep 1
venv/bin/python streamload.py --api &
PID=$!
sleep 4
kill $PID 2>/dev/null
```

Expected: no Python ImportError before the kill.

- [ ] **Step 4: Commit**

```bash
git add streamload.py
git commit -m "refactor(launcher): API-only mode — v1 CLI retired in v3"
```

---

## Phase D — Update routes to drop scraping coupling

### Task 12: Strip scraping from `streamload/catalog/ingest.py` and `streamload/catalog/worker.py`

**Files:**
- Modify: `streamload/catalog/ingest.py`
- Modify: `streamload/catalog/worker.py`

- [ ] **Step 1: Edit `streamload/catalog/ingest.py` — remove `_resolve_sources_for_item`, the `services` argument, and the `CatalogSource` import**

Open and apply:

```python
# Top of file: drop the CatalogSource import, keep the rest
from streamload.db.models import (
    CatalogItem,
    Collection,
    CollectionItem,
    TvEpisode,
)
```

Delete the entire function `_resolve_sources_for_item(...)` and the `REVERSE_LOOKUP_PER_SERVICE_TIMEOUT_SECONDS` constant + `REVERSE_LOOKUP_CONCURRENCY` constant.

In `ingest_collection`, change the signature and body:

```python
async def ingest_collection(
    db: AsyncSession,
    *,
    collection_id: str,
    collection_title: str,
    media_type: Optional[str],
    sort_order: int,
    refresh_ttl_hours: int,
    items: list[TmdbItem],
) -> None:
    """Full ingest cycle for a collection (TMDB metadata only — v3 has no
    server-side scraping)."""
    log.info("Ingesting collection %s (%d items)", collection_id, len(items))

    coll_stmt = insert(Collection).values(
        id=collection_id, title=collection_title, media_type=media_type,
        sort_order=sort_order, refresh_ttl_hours=refresh_ttl_hours,
        last_refreshed_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["id"],
        set_={
            "title": collection_title, "media_type": media_type,
            "sort_order": sort_order, "refresh_ttl_hours": refresh_ttl_hours,
            "last_refreshed_at": datetime.now(UTC),
        },
    )
    await db.execute(coll_stmt)

    for it in items:
        await _upsert_catalog_item(db, it)

    await db.execute(
        delete(CollectionItem).where(CollectionItem.collection_id == collection_id)
    )
    for pos, it in enumerate(items):
        db.add(CollectionItem(
            collection_id=collection_id, tmdb_id=it.tmdb_id,
            media_type=it.media_type, position=pos,
        ))

    await db.commit()
    log.info("Ingest complete for %s", collection_id)
```

In `ingest_single_title`, change the signature and body:

```python
async def ingest_single_title(
    db: AsyncSession,
    *,
    item: TmdbItem,
    tmdb: "TmdbClient | None" = None,
) -> None:
    """Ingest one title on-demand: TMDB metadata + (for tv) per-season episodes.

    No reverse-lookup: source resolution lives in the v3 client.
    """
    log.info("Lazy-ingest tmdb_id=%s (%s)", item.tmdb_id, item.title)
    await _upsert_catalog_item(db, item)

    if item.media_type == "tv" and tmdb is not None and (item.seasons_count or 0) > 0:
        try:
            n = await _ingest_tv_episodes(
                db, tmdb_id=item.tmdb_id, seasons_count=item.seasons_count, tmdb=tmdb,
            )
            log.info("Ingested %d episodes for tmdb=%s", n, item.tmdb_id)
        except Exception:
            log.warning("Episode ingestion failed for tmdb=%s", item.tmdb_id, exc_info=True)

    await db.commit()
    log.info("Lazy-ingest done: tmdb_id=%s", item.tmdb_id)
```

Drop the `import asyncio` if no longer used after the deletion (search the file; if `asyncio.Semaphore` is gone, remove it).

- [ ] **Step 2: Edit `streamload/catalog/worker.py` — remove the `_load_services` helper, drop `services` from `refresh_due_collections`**

```python
# Drop _load_services entirely.

async def refresh_due_collections(
    db: AsyncSession,
    *,
    tmdb_client: Any,
    collection_defs: Optional[list[CollectionDef]] = None,
) -> list[str]:
    """Refresh collections whose last_refreshed_at is older than their TTL."""
    defs = collection_defs if collection_defs is not None else COLLECTION_DEFS
    now = datetime.now(UTC)
    refreshed: list[str] = []
    for d in defs:
        existing = (await db.execute(
            select(Collection).where(Collection.id == d.id)
        )).scalar_one_or_none()
        if existing is not None and existing.last_refreshed_at is not None:
            age = now - existing.last_refreshed_at
            if age < timedelta(hours=d.refresh_ttl_hours):
                log.debug("Collection %s is fresh (age=%s)", d.id, age)
                continue
        log.info("Refreshing collection %s", d.id)
        items = await d.fetch(tmdb_client)
        await ingest_collection(
            db, collection_id=d.id, collection_title=d.title,
            media_type=d.media_type, sort_order=d.sort_order,
            refresh_ttl_hours=d.refresh_ttl_hours,
            items=items,
        )
        refreshed.append(d.id)
    return refreshed
```

In the `main()` function near the end, drop:

```python
    services = _load_services()
```

and the corresponding `services=services` kwarg in the inner `refresh_due_collections(...)` call.

- [ ] **Step 3: Update `streamload/api/app.py` `_run_catalog_refresh_loop` similarly**

In `streamload/api/app.py`, find `_run_catalog_refresh_loop`. Remove the `services = _load_services()` line and the `services=services` kwarg in `refresh_due_collections(...)`. The function should now look like:

```python
async def _run_catalog_refresh_loop() -> None:
    import httpx
    from streamload.catalog.tmdb import TmdbClient
    from streamload.catalog.worker import POLL_INTERVAL_SECONDS, refresh_due_collections
    from streamload.db.session import _session_factory

    api_key = os.environ.get("TMDB_API_KEY", "")
    if not api_key:
        log.warning("Catalog refresh disabled: TMDB_API_KEY missing")
        return

    await asyncio.sleep(5)

    while True:
        try:
            async with _session_factory() as db:
                async with httpx.AsyncClient(timeout=20) as http:
                    tmdb = TmdbClient(api_key=api_key, http=http)
                    refreshed = await refresh_due_collections(
                        db, tmdb_client=tmdb,
                    )
                    if refreshed:
                        log.info("Catalog refreshed: %s", ", ".join(refreshed))
        except asyncio.CancelledError:
            raise
        except Exception:
            log.error("Catalog refresh tick failed", exc_info=True)
        await asyncio.sleep(POLL_INTERVAL_SECONDS)
```

- [ ] **Step 4: Smoke-test app boot**

```bash
venv/bin/python -c "from streamload.api.app import create_app; print('OK', len(create_app().routes))"
```

Expected: prints `OK <int>` (no exception). The route count should be ~46.

- [ ] **Step 5: Commit**

```bash
git add streamload/catalog/ingest.py streamload/catalog/worker.py streamload/api/app.py
git commit -m "refactor(catalog): drop reverse-lookup — server is metadata-only in v3"
```

---

### Task 13: Strip scraping from `streamload/api/routes/catalog.py`

**Files:**
- Modify: `streamload/api/routes/catalog.py`

- [ ] **Step 1: Update the failing test FIRST**

Edit `tests/api/test_catalog.py`. Find `test_get_catalog_item` and adjust:

```python
@pytest.mark.asyncio
async def test_get_catalog_item(api_client, authed):
    async for db in gs():
        db.add(CatalogItem(tmdb_id=42, media_type="movie", title="Foo", year=2024))
        await db.commit()
        break
    r = await api_client.get("/api/catalog/42?media_type=movie")
    assert r.status_code == 200
    body = r.json()
    assert body["title"] == "Foo"
    # v3: server never knows sources — they live in the client.
    assert body["sources"] == []
```

Drop the `from streamload.db.models import CatalogSource` import (or the multi-import if it includes CatalogSource).

- [ ] **Step 2: Run, expect failure on assert sources == []**

```bash
venv/bin/python -m pytest tests/api/test_catalog.py::test_get_catalog_item -v
```

Expected: AssertionError or ImportError (CatalogSource is gone).

- [ ] **Step 3: Rewrite `streamload/api/routes/catalog.py`**

Replace the entire file with:

```python
"""Catalog detail endpoint.

v3: pure metadata mirror. Lazy-ingest pulls from TMDB when the title isn't
yet cached; sources are never resolved server-side and are always returned
as an empty list. The client resolves sources locally via its plugin runtime.
"""
from __future__ import annotations

import os
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel

from streamload.api.deps import CurrentUser, SessionDep
from streamload.catalog.ingest import ingest_single_title
from streamload.catalog.service import CatalogService
from streamload.catalog.tmdb import TmdbClient, TmdbItem
from streamload.utils.logger import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/catalog", tags=["catalog"])


class SourceResponse(BaseModel):
    label: str
    score: float


class CatalogItemResponse(BaseModel):
    tmdb_id: int
    media_type: str
    title: str
    original_title: str | None
    year: int | None
    poster_url: str | None
    backdrop_url: str | None
    overview: str | None
    rating: float | None
    runtime_minutes: int | None
    seasons_count: int | None
    genres: list[str]
    sources: list[SourceResponse]   # always [] in v3 server response


async def _fetch_tmdb_item(
    client: TmdbClient, tmdb_id: int, media_type: Optional[str],
) -> Optional[TmdbItem]:
    order = ["movie", "tv"] if media_type != "tv" else ["tv", "movie"]
    for mt in order:
        try:
            return await client.get_movie(tmdb_id) if mt == "movie" else await client.get_tv(tmdb_id)
        except httpx.HTTPStatusError as e:
            if e.response.status_code != 404:
                log.warning("TMDB %s/%s error: %s", mt, tmdb_id, e)
            continue
        except Exception:
            log.warning("TMDB lookup failed for %s/%s", mt, tmdb_id, exc_info=True)
            continue
    return None


@router.get("/{tmdb_id}", response_model=CatalogItemResponse)
async def get_item(
    tmdb_id: int,
    db: SessionDep,
    user: CurrentUser,
    media_type: Optional[str] = None,
) -> CatalogItemResponse:
    svc = CatalogService(db)
    item = await svc.get_item(tmdb_id, media_type=media_type)

    if item is None:
        api_key = os.environ.get("TMDB_API_KEY", "")
        if not api_key:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found in catalog")
        async with httpx.AsyncClient(timeout=15) as http:
            tmdb = TmdbClient(api_key=api_key, http=http)
            tmdb_item = await _fetch_tmdb_item(tmdb, tmdb_id, media_type)
            if tmdb_item is None:
                raise HTTPException(status.HTTP_404_NOT_FOUND, "title not found on TMDB")
            await ingest_single_title(db, item=tmdb_item, tmdb=tmdb)
        item = await svc.get_item(tmdb_id, media_type=tmdb_item.media_type)
        if item is None:
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "ingest failed")

    return CatalogItemResponse(
        tmdb_id=item.tmdb_id,
        media_type=item.media_type,
        title=item.title,
        original_title=item.original_title,
        year=item.year,
        poster_url=item.poster_url,
        backdrop_url=item.backdrop_url,
        overview=item.overview,
        rating=float(item.rating) if item.rating is not None else None,
        runtime_minutes=item.runtime_minutes,
        seasons_count=item.seasons_count,
        genres=item.genres,
        sources=[],
    )
```

This drops: the `_ranked_sources()` helper, the episode backfill check (which queried CatalogSource), the `_refresh_one()` function, and the `admin_router` block.

- [ ] **Step 4: Update `streamload/catalog/service.py` — remove `selectinload(CatalogItem.sources)` since the relationship no longer exists**

Edit `streamload/catalog/service.py`. In `get_item`:

```python
# Before
from sqlalchemy.orm import selectinload
...
stmt = (
    select(CatalogItem)
    .options(selectinload(CatalogItem.sources))
    .where(CatalogItem.tmdb_id == tmdb_id)
)

# After (drop the .options() call AND the selectinload import if unused)
stmt = (
    select(CatalogItem)
    .where(CatalogItem.tmdb_id == tmdb_id)
)
```

Also drop the `CatalogSource` import at the top of `service.py` if present.

- [ ] **Step 5: Run catalog tests**

```bash
venv/bin/python -m pytest tests/api/test_catalog.py tests/catalog/ -v
```

Expected: all pass.

- [ ] **Step 6: Commit**

```bash
git add streamload/api/routes/catalog.py streamload/catalog/service.py tests/api/test_catalog.py
git commit -m "refactor(catalog): TMDB-only lazy-ingest; sources always [] in v3 server"
```

---

### Task 14: Strip the catalog-source KPI and domain-resolver health from admin

**Files:**
- Modify: `streamload/api/routes/admin.py`
- Modify: `tests/api/test_admin.py` (drop admin_refresh test file already deleted in Task 6)

- [ ] **Step 1: Edit `streamload/api/routes/admin.py`**

Find the `stats()` endpoint. Drop the `total_sources` lookup and the field from the response model.

```python
# Before — in CatalogStats model
class CatalogStats(BaseModel):
    total_items: int
    total_sources: int   # ← DROP
    total_users: int
    ...

# After
class CatalogStats(BaseModel):
    total_items: int
    total_users: int
    active_users: int
    disabled_users: int
    completed_views_30d: int
```

In the `stats()` function body, remove the line:

```python
sources = (await db.execute(select(func.count()).select_from(CatalogSource))).scalar_one()
```

and the `from streamload.db.models import CatalogSource` import.

In the `return CatalogStats(...)` call, drop the `total_sources=sources,` argument.

Find the `/admin/health/domains` endpoint and DELETE the entire function:

```python
@router.get("/health/domains")
async def domains_health(admin: AdminUser) -> dict:
    """Show resolver state per service: cached domain, source, last verified."""
    from pathlib import Path
    from streamload.utils.domain_resolver.cache import DomainCache
    cache = DomainCache(Path("data/domains_cache.json"))
    return {"entries": cache.entries()}
```

- [ ] **Step 2: Update `tests/api/test_admin.py`**

If any test asserts on `body["total_sources"]` or hits `/admin/health/domains`, remove that assertion. Most likely the existing tests don't (we have only test_admin_can_list_users, test_admin_can_disable_user, etc.). Verify with:

```bash
grep -n "total_sources\|health/domains" tests/api/test_admin.py
```

Expected: empty output. If anything appears, delete the matching lines.

- [ ] **Step 3: Run admin tests**

```bash
venv/bin/python -m pytest tests/api/test_admin.py -v
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add streamload/api/routes/admin.py tests/api/test_admin.py
git commit -m "refactor(admin): drop total_sources KPI + /admin/health/domains"
```

---

### Task 15: Strip `last_source` from `progress.py` + auto-fill `watch_history`

**Files:**
- Modify: `streamload/api/routes/progress.py`
- Modify: `tests/api/test_progress.py`

- [ ] **Step 1: Update the failing test FIRST**

In `tests/api/test_progress.py`, drop `"source": "sc"` from every payload. Add a new test for watch_history insertion:

```python
@pytest.mark.asyncio
async def test_post_progress_inserts_watch_history_on_completion(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import WatchHistory
    # >90% triggers completion
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie",
        "position_seconds": 6500, "duration_seconds": 7200,
    })
    async for db in gs():
        rows = (await db.execute(select(WatchHistory))).scalars().all()
        assert len(rows) == 1
        assert rows[0].tmdb_id == 42
        assert rows[0].media_type == "movie"
        break


@pytest.mark.asyncio
async def test_post_progress_no_history_when_not_completed(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import WatchHistory
    await api_client.post("/api/progress", json={
        "tmdb_id": 42, "media_type": "movie",
        "position_seconds": 100, "duration_seconds": 7200,
    })
    async for db in gs():
        rows = (await db.execute(select(WatchHistory))).scalars().all()
        assert rows == []
        break
```

- [ ] **Step 2: Run — expect failures**

```bash
venv/bin/python -m pytest tests/api/test_progress.py -v
```

Expected: failures on the new tests (WatchHistory rows missing) and possibly on existing tests if `source` field is now rejected by the new schema.

- [ ] **Step 3: Edit `streamload/api/routes/progress.py`**

Replace the file with:

```python
"""Watch progress endpoints (v3 — no last_source field, watch_history side-effect)."""
from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, WatchHistory, WatchProgress

router = APIRouter(tags=["progress"])

WATCHED_THRESHOLD = 0.90


class PostProgressRequest(BaseModel):
    tmdb_id: int
    media_type: str = Field(pattern="^(movie|tv)$")
    season_number: int | None = None
    episode_number: int | None = None
    position_seconds: int = Field(ge=0)
    duration_seconds: int = Field(ge=1)


class ProgressItem(BaseModel):
    tmdb_id: int
    media_type: str
    season_number: int | None
    episode_number: int | None
    position_seconds: int
    duration_seconds: int
    title: str
    poster_url: str | None


class ContinueWatchingResponse(BaseModel):
    items: list[ProgressItem]


@router.post("/progress")
async def post_progress(payload: PostProgressRequest, user: CurrentUser, db: SessionDep) -> dict[str, str]:
    completed = (payload.position_seconds / payload.duration_seconds) >= WATCHED_THRESHOLD

    # Was this row already completed before this update? Used to gate the
    # watch_history insertion (only on the false → true transition).
    prior = (await db.execute(
        select(WatchProgress.completed).where(
            WatchProgress.user_id == user.id,
            WatchProgress.tmdb_id == payload.tmdb_id,
            WatchProgress.media_type == payload.media_type,
            WatchProgress.season_number == (payload.season_number or 0),
            WatchProgress.episode_number == (payload.episode_number or 0),
        )
    )).scalar_one_or_none()
    was_completed = bool(prior) if prior is not None else False

    stmt = insert(WatchProgress).values(
        user_id=user.id,
        tmdb_id=payload.tmdb_id,
        media_type=payload.media_type,
        season_number=payload.season_number or 0,
        episode_number=payload.episode_number or 0,
        position_seconds=payload.position_seconds,
        duration_seconds=payload.duration_seconds,
        completed=completed,
        updated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["user_id", "tmdb_id", "media_type", "season_number", "episode_number"],
        set_={
            "position_seconds": payload.position_seconds,
            "duration_seconds": payload.duration_seconds,
            "completed": completed,
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)

    if completed and not was_completed:
        db.add(WatchHistory(
            user_id=user.id,
            tmdb_id=payload.tmdb_id,
            media_type=payload.media_type,
            season_number=payload.season_number or 0,
            episode_number=payload.episode_number or 0,
            completed_at=datetime.now(UTC),
        ))

    await db.commit()
    return {"status": "ok", "completed": str(completed).lower()}


@router.get("/progress/continue-watching", response_model=ContinueWatchingResponse)
async def continue_watching(user: CurrentUser, db: SessionDep) -> ContinueWatchingResponse:
    stmt = (
        select(WatchProgress, CatalogItem)
        .join(
            CatalogItem,
            (CatalogItem.tmdb_id == WatchProgress.tmdb_id)
            & (CatalogItem.media_type == WatchProgress.media_type),
        )
        .where(WatchProgress.user_id == user.id)
        .where(WatchProgress.completed.is_(False))
        .order_by(WatchProgress.updated_at.desc())
        .limit(20)
    )
    rows = (await db.execute(stmt)).all()
    return ContinueWatchingResponse(items=[
        ProgressItem(
            tmdb_id=p.tmdb_id,
            media_type=p.media_type,
            season_number=p.season_number if p.season_number else None,
            episode_number=p.episode_number if p.episode_number else None,
            position_seconds=p.position_seconds,
            duration_seconds=p.duration_seconds,
            title=item.title,
            poster_url=item.poster_url,
        ) for p, item in rows
    ])
```

- [ ] **Step 4: Run progress tests, expect green**

```bash
venv/bin/python -m pytest tests/api/test_progress.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/progress.py tests/api/test_progress.py
git commit -m "refactor(progress): drop last_source; insert watch_history on completion"
```

---

## Phase E — New endpoints

### Task 16: New `next_up.py` route

**Files:**
- Create: `streamload/api/routes/next_up.py`
- Create: `tests/api/test_next_up.py`
- Modify: `streamload/api/app.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/api/test_next_up.py`:

```python
"""Tests for /next-up endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs
from streamload.db.models import CatalogItem, TvEpisode


@pytest_asyncio.fixture
async def authed_with_series(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "nu_user", "email": "nu@x.com", "password": "Hunter2!secret",
    })
    async for db in gs():
        db.add(CatalogItem(tmdb_id=99, media_type="tv", title="Show", seasons_count=2))
        db.add_all([
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=1, title="S1E1"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=2, title="S1E2"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=1, episode_number=3, title="S1E3"),
            TvEpisode(tmdb_id=99, media_type="tv", season_number=2, episode_number=1, title="S2E1"),
        ])
        await db.commit()
        break


@pytest.mark.asyncio
async def test_next_up_returns_next_episode_in_same_season(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=1&episode=2")
    assert r.status_code == 200
    body = r.json()
    assert body["season_number"] == 1
    assert body["episode_number"] == 3


@pytest.mark.asyncio
async def test_next_up_jumps_to_next_season_when_at_finale(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=1&episode=3")
    assert r.status_code == 200
    body = r.json()
    assert body["season_number"] == 2
    assert body["episode_number"] == 1


@pytest.mark.asyncio
async def test_next_up_returns_204_at_series_end(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/99?season=2&episode=1")
    assert r.status_code == 204


@pytest.mark.asyncio
async def test_next_up_404_for_unknown_title(api_client, authed_with_series):
    r = await api_client.get("/api/next-up/9999?season=1&episode=1")
    assert r.status_code == 404
```

- [ ] **Step 2: Run, expect 404 (route doesn't exist yet)**

```bash
venv/bin/python -m pytest tests/api/test_next_up.py -v
```

Expected: all 4 fail with 404 from FastAPI (no such route).

- [ ] **Step 3: Create `streamload/api/routes/next_up.py`**

```python
"""Next-up endpoint: given (tmdb_id, season, episode), return the next episode."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel
from sqlalchemy import select

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import CatalogItem, TvEpisode

router = APIRouter(tags=["next-up"])


class NextEpisode(BaseModel):
    tmdb_id: int
    season_number: int
    episode_number: int
    title: str | None
    still_url: str | None


@router.get("/next-up/{tmdb_id}")
async def next_up(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    response: Response,
    season: int = Query(..., ge=1),
    episode: int = Query(..., ge=1),
) -> NextEpisode | None:
    series = (await db.execute(
        select(CatalogItem).where(
            CatalogItem.tmdb_id == tmdb_id,
            CatalogItem.media_type == "tv",
        )
    )).scalar_one_or_none()
    if series is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "series not found")

    next_in_season = (await db.execute(
        select(TvEpisode)
        .where(
            TvEpisode.tmdb_id == tmdb_id,
            TvEpisode.media_type == "tv",
            TvEpisode.season_number == season,
            TvEpisode.episode_number > episode,
        )
        .order_by(TvEpisode.episode_number.asc())
        .limit(1)
    )).scalar_one_or_none()
    if next_in_season is not None:
        return NextEpisode(
            tmdb_id=tmdb_id,
            season_number=next_in_season.season_number,
            episode_number=next_in_season.episode_number,
            title=next_in_season.title,
            still_url=next_in_season.still_url,
        )

    first_of_next_season = (await db.execute(
        select(TvEpisode)
        .where(
            TvEpisode.tmdb_id == tmdb_id,
            TvEpisode.media_type == "tv",
            TvEpisode.season_number > season,
        )
        .order_by(TvEpisode.season_number.asc(), TvEpisode.episode_number.asc())
        .limit(1)
    )).scalar_one_or_none()
    if first_of_next_season is not None:
        return NextEpisode(
            tmdb_id=tmdb_id,
            season_number=first_of_next_season.season_number,
            episode_number=first_of_next_season.episode_number,
            title=first_of_next_season.title,
            still_url=first_of_next_season.still_url,
        )

    response.status_code = status.HTTP_204_NO_CONTENT
    return None
```

- [ ] **Step 4: Wire it in `streamload/api/app.py`**

Add to imports and include:

```python
# In the routes import line:
from .routes import admin, auth, catalog, collections, email, episodes, events, favorites, health, intro, library, me, next_up, passkey, progress, search, settings, watchlist

# In create_app():
    app.include_router(next_up.router, prefix="/api")
```

(The `events` import will be used in Task 17.)

- [ ] **Step 5: Run tests**

```bash
venv/bin/python -m pytest tests/api/test_next_up.py -v
```

Expected: all 4 pass.

- [ ] **Step 6: Commit**

```bash
git add streamload/api/routes/next_up.py streamload/api/app.py tests/api/test_next_up.py
git commit -m "feat(api): GET /next-up/{tmdb_id}?season=&episode= for smart resume"
```

---

### Task 17: New `events.py` route (telemetry batch ingestion)

**Files:**
- Create: `streamload/api/routes/events.py`
- Create: `tests/api/test_events.py`
- Modify: `streamload/api/app.py`

- [ ] **Step 1: Write failing tests**

Create `tests/api/test_events.py`:

```python
"""Tests for /events telemetry endpoint."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio

from streamload.db import get_session as gs


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "evt_user", "email": "evt@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_post_events_accepts_valid_batch(api_client, authed):
    r = await api_client.post("/api/events", json={
        "app_version": "0.3.0",
        "events": [
            {"event_type": "app.start", "payload": {"app_version": "0.3.0", "os": "macos", "locale": "it-IT"}},
            {"event_type": "catalog.view", "payload": {"tmdb_id": 1396, "media_type": "tv"}},
        ],
    })
    assert r.status_code == 202

    from sqlalchemy import select
    from streamload.db.models import Event
    async for db in gs():
        rows = (await db.execute(select(Event).order_by(Event.id))).scalars().all()
        assert len(rows) == 2
        assert rows[0].event_type == "app.start"
        assert rows[0].user_id is not None
        assert rows[0].app_version == "0.3.0"
        assert rows[1].event_type == "catalog.view"
        assert rows[1].payload == {"tmdb_id": 1396, "media_type": "tv"}
        break


@pytest.mark.asyncio
async def test_post_events_rejects_unknown_event_type(api_client, authed):
    r = await api_client.post("/api/events", json={
        "events": [
            {"event_type": "totally.invented", "payload": {}},
        ],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_events_rejects_oversized_batch(api_client, authed):
    r = await api_client.post("/api/events", json={
        "events": [
            {"event_type": "app.start", "payload": {}}
            for _ in range(101)
        ],
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_events_requires_auth(api_client):
    r = await api_client.post("/api/events", json={"events": []})
    assert r.status_code == 401
```

- [ ] **Step 2: Run, expect failures (no route)**

```bash
venv/bin/python -m pytest tests/api/test_events.py -v
```

Expected: all fail (404 or 405).

- [ ] **Step 3: Create `streamload/api/routes/events.py`**

```python
"""Telemetry ingestion: client posts batched events captured per spec §5.4."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import Event

router = APIRouter(tags=["events"])

# Closed enum from spec §5.4. Anything outside this list is rejected at
# validation time so we never accumulate garbage event types in analytics.
ALLOWED_EVENT_TYPES = {
    "auth.login_success",
    "auth.login_failed",
    "auth.logout",
    "auth.passkey_register",
    "catalog.view",
    "search.run",
    "play.start",
    "play.complete",
    "favorite.add",
    "favorite.remove",
    "watchlist.add",
    "watchlist.remove",
    "app.start",
    "plugin_pack.installed",
    "plugin_pack.updated",
}


class EventIn(BaseModel):
    event_type: str
    payload: dict = Field(default_factory=dict)


class BatchIn(BaseModel):
    app_version: str | None = None
    events: Annotated[list[EventIn], Field(min_length=0, max_length=100)]


@router.post("/events", status_code=202)
async def post_events(
    payload: BatchIn,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
) -> dict[str, int]:
    # Validate event types up front; reject the whole batch on any unknown.
    for ev in payload.events:
        if ev.event_type not in ALLOWED_EVENT_TYPES:
            from fastapi import HTTPException, status as http_status
            raise HTTPException(
                http_status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"unknown event_type {ev.event_type!r}",
            )

    ip = request.client.host if request.client else None
    user_agent = request.headers.get("user-agent")
    now = datetime.now(UTC)

    for ev in payload.events:
        db.add(Event(
            user_id=user.id,
            event_type=ev.event_type,
            payload=ev.payload,
            ip=ip,
            user_agent=user_agent,
            app_version=payload.app_version,
            occurred_at=now,
        ))
    await db.commit()
    return {"accepted": len(payload.events)}
```

- [ ] **Step 4: Include the router in `streamload/api/app.py`**

Add (the import was already added in Task 16):

```python
    app.include_router(events.router, prefix="/api")
```

- [ ] **Step 5: Run tests**

```bash
venv/bin/python -m pytest tests/api/test_events.py -v
```

Expected: all 4 pass.

- [ ] **Step 6: Commit**

```bash
git add streamload/api/routes/events.py streamload/api/app.py tests/api/test_events.py
git commit -m "feat(api): POST /events for batched telemetry ingestion"
```

---

### Task 18: Replace stub `settings.py` with DB-backed UserSettings

**Files:**
- Modify: `streamload/api/routes/settings.py`
- Modify: `tests/api/test_settings.py`

- [ ] **Step 1: Write failing tests (replace existing)**

Replace `tests/api/test_settings.py` entirely:

```python
"""Tests for the /settings endpoint (v3 — DB-backed)."""
from __future__ import annotations

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def authed(api_client: httpx.AsyncClient):
    await api_client.post("/api/auth/register", json={
        "username": "set_user", "email": "set@x.com", "password": "Hunter2!secret",
    })


@pytest.mark.asyncio
async def test_get_settings_returns_defaults_for_new_user(api_client, authed):
    r = await api_client.get("/api/settings")
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref_lang"] == "ita"
    assert body["subs_pref_lang"] == "ita"
    assert body["autoplay_next_episode"] is True
    assert body["skip_intro"] is True
    assert body["theme"] == "auto"
    assert body["locale"] == "it-IT"
    assert body["quality_cap_height"] is None


@pytest.mark.asyncio
async def test_put_settings_persists_changes(api_client, authed):
    r = await api_client.put("/api/settings", json={
        "audio_pref_lang": "eng",
        "subs_pref_lang": "ita",
        "autoplay_next_episode": False,
        "skip_intro": False,
        "theme": "dark",
        "locale": "en-US",
        "quality_cap_height": 1080,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["audio_pref_lang"] == "eng"
    assert body["theme"] == "dark"
    assert body["quality_cap_height"] == 1080

    # Round-trip: GET reflects what was PUT
    r = await api_client.get("/api/settings")
    body2 = r.json()
    assert body2["audio_pref_lang"] == "eng"
    assert body2["theme"] == "dark"


@pytest.mark.asyncio
async def test_put_settings_rejects_invalid_theme(api_client, authed):
    r = await api_client.put("/api/settings", json={
        "audio_pref_lang": "ita",
        "subs_pref_lang": "ita",
        "autoplay_next_episode": True,
        "skip_intro": True,
        "theme": "rainbow",
        "locale": "it-IT",
        "quality_cap_height": None,
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_settings_requires_auth(api_client):
    r = await api_client.get("/api/settings")
    assert r.status_code == 401
```

- [ ] **Step 2: Run, expect failures**

```bash
venv/bin/python -m pytest tests/api/test_settings.py -v
```

Expected: failures (current stub returns hardcoded defaults, doesn't persist, doesn't validate theme).

- [ ] **Step 3: Replace `streamload/api/routes/settings.py`**

```python
"""Per-user preferences — v3 DB-backed via user_settings table."""
from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from streamload.api.deps import CurrentUser, SessionDep
from streamload.db.models import UserSettings as UserSettingsRow

router = APIRouter(prefix="/settings", tags=["settings"])


Theme = Literal["auto", "light", "dark"]


class UserSettings(BaseModel):
    audio_pref_lang: str = "ita"
    subs_pref_lang: str = "ita"
    quality_cap_height: int | None = None
    autoplay_next_episode: bool = True
    skip_intro: bool = True
    theme: Theme = "auto"
    locale: str = "it-IT"


def _row_to_model(row: UserSettingsRow) -> UserSettings:
    return UserSettings(
        audio_pref_lang=row.audio_pref_lang,
        subs_pref_lang=row.subs_pref_lang,
        quality_cap_height=row.quality_cap_height,
        autoplay_next_episode=row.autoplay_next_episode,
        skip_intro=row.skip_intro,
        theme=row.theme,
        locale=row.locale,
    )


@router.get("", response_model=UserSettings)
async def get_settings(user: CurrentUser, db: SessionDep) -> UserSettings:
    row = (await db.execute(
        select(UserSettingsRow).where(UserSettingsRow.user_id == user.id)
    )).scalar_one_or_none()
    if row is None:
        # Defaults baked into UserSettings(); not persisted until PUT.
        return UserSettings()
    return _row_to_model(row)


@router.put("", response_model=UserSettings)
async def update_settings(
    payload: UserSettings, user: CurrentUser, db: SessionDep,
) -> UserSettings:
    stmt = insert(UserSettingsRow).values(
        user_id=user.id,
        audio_pref_lang=payload.audio_pref_lang,
        subs_pref_lang=payload.subs_pref_lang,
        quality_cap_height=payload.quality_cap_height,
        autoplay_next_episode=payload.autoplay_next_episode,
        skip_intro=payload.skip_intro,
        theme=payload.theme,
        locale=payload.locale,
        updated_at=datetime.now(UTC),
    ).on_conflict_do_update(
        index_elements=["user_id"],
        set_={
            "audio_pref_lang": payload.audio_pref_lang,
            "subs_pref_lang": payload.subs_pref_lang,
            "quality_cap_height": payload.quality_cap_height,
            "autoplay_next_episode": payload.autoplay_next_episode,
            "skip_intro": payload.skip_intro,
            "theme": payload.theme,
            "locale": payload.locale,
            "updated_at": datetime.now(UTC),
        },
    )
    await db.execute(stmt)
    await db.commit()
    return payload
```

- [ ] **Step 4: Run, expect green**

```bash
venv/bin/python -m pytest tests/api/test_settings.py -v
```

Expected: all 4 pass.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/settings.py tests/api/test_settings.py
git commit -m "feat(settings): persist user preferences in user_settings table"
```

---

## Phase F — Server-side telemetry emission

These tasks insert event rows from inside the routes that already mutate state. The client doesn't need to post these — they're free.

### Task 19: Helper for inserting events

**Files:**
- Create: `streamload/api/telemetry.py`

- [ ] **Step 1: Create the helper**

```python
"""Server-side telemetry helper.

Routes call `await emit(db, request, user_id, event_type, payload)` after a
successful mutation. The same closed enum as /events validates type names.

This is for server-driven events (auth/favorites/watchlist mutations);
client-driven events (catalog.view, play.start/complete, app.start) come in
via POST /api/events instead.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Optional

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from streamload.db.models import Event


async def emit(
    db: AsyncSession,
    request: Request,
    *,
    user_id: Optional[uuid.UUID],
    event_type: str,
    payload: Optional[dict] = None,
) -> None:
    """Insert one event. Caller commits as part of the surrounding transaction."""
    db.add(Event(
        user_id=user_id,
        event_type=event_type,
        payload=payload or {},
        ip=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
        app_version=None,  # only populated for client-posted events
        occurred_at=datetime.now(UTC),
    ))
```

No test file needed — exercised through the routes that use it (Tasks 20-22).

- [ ] **Step 2: Commit**

```bash
git add streamload/api/telemetry.py
git commit -m "feat(api): telemetry.emit helper for server-side event capture"
```

---

### Task 20: Wire telemetry into `auth.py` (login_success / login_failed / logout)

**Files:**
- Modify: `streamload/api/routes/auth.py`
- Modify: `tests/api/test_auth_login.py`

- [ ] **Step 1: Add a failing test**

Append to `tests/api/test_auth_login.py`:

```python
@pytest.mark.asyncio
async def test_login_success_emits_telemetry_event(api_client: httpx.AsyncClient):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "tel_user", "email": "tel@x.com", "password": "Hunter2!secret",
    })
    await api_client.post("/api/auth/logout")
    await api_client.post("/api/auth/login", json={
        "username": "tel_user", "password": "Hunter2!secret",
    })

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event).order_by(Event.id)
        )).scalars().all()]
        assert "auth.login_success" in types
        assert "auth.logout" in types
        break


@pytest.mark.asyncio
async def test_login_failed_emits_telemetry_event(api_client: httpx.AsyncClient):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "tel_user2", "email": "tel2@x.com", "password": "Hunter2!secret",
    })
    await api_client.post("/api/auth/logout")
    r = await api_client.post("/api/auth/login", json={
        "username": "tel_user2", "password": "wrong-password",
    })
    assert r.status_code == 401

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event)
        )).scalars().all()]
        assert "auth.login_failed" in types
        break
```

- [ ] **Step 2: Run, expect failures**

```bash
venv/bin/python -m pytest tests/api/test_auth_login.py -v
```

Expected: the two new tests fail (no events written yet).

- [ ] **Step 3: Edit `streamload/api/routes/auth.py`**

Add the import:

```python
from streamload.api.telemetry import emit as emit_event
```

In `login()`, modify around the credential check:

```python
    if user is None or not user.password_hash:
        await emit_event(db, request, user_id=None, event_type="auth.login_failed",
                         payload={"reason": "unknown_user"})
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if not verify_password(user.password_hash, payload.password):
        await emit_event(db, request, user_id=user.id, event_type="auth.login_failed",
                         payload={"reason": "bad_password"})
        await db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid credentials")
    if user.disabled_at is not None:
        await emit_event(db, request, user_id=user.id, event_type="auth.login_failed",
                         payload={"reason": "disabled"})
        await db.commit()
        raise HTTPException(status.HTTP_403_FORBIDDEN, "account disabled")

    user.last_login_at = datetime.now(UTC)

    # ... existing session creation ...

    await emit_event(db, request, user_id=user.id, event_type="auth.login_success")
    await db.commit()
```

In `logout()`, add before `await db.commit()` if a user is loadable from the session, OR just emit unconditionally:

```python
    user_id = None
    if token:
        # The session is being deleted; we still want to know who logged out.
        from streamload.db.models import Session
        from sqlalchemy import select
        sess = (await db.execute(
            select(Session).where(Session.token == token)
        )).scalar_one_or_none()
        if sess:
            user_id = sess.user_id
        await delete_session(db, token=token)
    await emit_event(db, request, user_id=user_id, event_type="auth.logout")
    await db.commit()
    response.delete_cookie("session")
```

(If your existing `Session` model doesn't have a `token` column, look at the model: it has `token_hash` instead. Hash the token before lookup. Skip user_id capture if the schema makes it awkward — emit with `user_id=None`.)

- [ ] **Step 4: Run, expect green**

```bash
venv/bin/python -m pytest tests/api/test_auth_login.py -v
```

Expected: all pass (including the two new ones).

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/auth.py tests/api/test_auth_login.py
git commit -m "feat(telemetry): emit auth.login_success/failed/logout events"
```

---

### Task 21: Wire telemetry into `favorites.py` and `watchlist.py`

**Files:**
- Modify: `streamload/api/routes/favorites.py`
- Modify: `streamload/api/routes/watchlist.py`
- Modify: `tests/api/test_favorites.py`
- Modify: `tests/api/test_watchlist.py`

- [ ] **Step 1: Add failing tests**

Append to `tests/api/test_favorites.py`:

```python
@pytest.mark.asyncio
async def test_add_favorite_emits_event(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/favorites/99?media_type=movie")

    async for db in gs():
        rows = (await db.execute(
            select(Event).where(Event.event_type == "favorite.add")
        )).scalars().all()
        assert len(rows) == 1
        assert rows[0].payload == {"tmdb_id": 99, "media_type": "movie"}
        break


@pytest.mark.asyncio
async def test_remove_favorite_emits_event(api_client, authed_with_item):
    from sqlalchemy import select
    from streamload.db.models import Event
    from streamload.db import get_session as gs

    await api_client.post("/api/favorites/99?media_type=movie")
    await api_client.delete("/api/favorites/99?media_type=movie")

    async for db in gs():
        types = [e.event_type for e in (await db.execute(
            select(Event)
        )).scalars().all()]
        assert "favorite.add" in types
        assert "favorite.remove" in types
        break
```

Same shape for `tests/api/test_watchlist.py` (use `watchlist.add` / `watchlist.remove`, tmdb_id 77, media_type "tv").

- [ ] **Step 2: Run, expect failures**

```bash
venv/bin/python -m pytest tests/api/test_favorites.py tests/api/test_watchlist.py -v
```

Expected: the new tests fail.

- [ ] **Step 3: Edit `streamload/api/routes/favorites.py`**

Add import + emit in both routes:

```python
from fastapi import APIRouter, Query, Request
from streamload.api.telemetry import emit as emit_event

@router.post("/{tmdb_id}", status_code=201)
async def add_favorite(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> dict[str, str]:
    stmt = insert(Favorite).values(
        user_id=user.id, tmdb_id=tmdb_id, media_type=media_type,
    ).on_conflict_do_nothing()
    await db.execute(stmt)
    await emit_event(db, request, user_id=user.id, event_type="favorite.add",
                     payload={"tmdb_id": tmdb_id, "media_type": media_type})
    await db.commit()
    return {"status": "added"}


@router.delete("/{tmdb_id}", status_code=204)
async def remove_favorite(
    tmdb_id: int,
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    media_type: str = Query(..., pattern="^(movie|tv)$"),
) -> None:
    await db.execute(
        delete(Favorite)
        .where(Favorite.user_id == user.id)
        .where(Favorite.tmdb_id == tmdb_id)
        .where(Favorite.media_type == media_type)
    )
    await emit_event(db, request, user_id=user.id, event_type="favorite.remove",
                     payload={"tmdb_id": tmdb_id, "media_type": media_type})
    await db.commit()
```

Identical pattern for `streamload/api/routes/watchlist.py` (substitute `Watchlist` model and `watchlist.add` / `watchlist.remove` event types).

- [ ] **Step 4: Run, expect green**

```bash
venv/bin/python -m pytest tests/api/test_favorites.py tests/api/test_watchlist.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/favorites.py streamload/api/routes/watchlist.py tests/api/test_favorites.py tests/api/test_watchlist.py
git commit -m "feat(telemetry): emit favorite/watchlist add/remove events"
```

---

### Task 22: Wire telemetry into `passkey.py` (passkey_register)

**Files:**
- Modify: `streamload/api/routes/passkey.py`

- [ ] **Step 1: Add the emit call**

Open `streamload/api/routes/passkey.py`. Find the `register/complete` (or `register_finish`) endpoint that returns a successful registration. Add:

```python
from fastapi import Request
from streamload.api.telemetry import emit as emit_event

# In the function signature, add `request: Request,`
# After the credential is committed:
await emit_event(db, request, user_id=user.id, event_type="auth.passkey_register")
await db.commit()
```

If the function already commits before this point, do the emit + commit BEFORE the response.

- [ ] **Step 2: Smoke-test the passkey suite still passes**

```bash
venv/bin/python -m pytest tests/api/test_passkey.py -v
```

Expected: all pass (passkey_register tests don't assert on the event yet — that's fine).

- [ ] **Step 3: Commit**

```bash
git add streamload/api/routes/passkey.py
git commit -m "feat(telemetry): emit auth.passkey_register on completion"
```

---

### Task 23: Wire telemetry into `search.py` (search.run + search_history insert)

**Files:**
- Modify: `streamload/api/routes/search.py`
- Modify: `tests/api/test_search.py`

- [ ] **Step 1: Write failing test**

Append to `tests/api/test_search.py`:

```python
@pytest.mark.asyncio
async def test_search_inserts_search_history_and_event(api_client: httpx.AsyncClient):
    import hashlib
    from sqlalchemy import select
    from streamload.db.models import Event, SearchHistory
    from streamload.db import get_session as gs

    await api_client.post("/api/auth/register", json={
        "username": "src_user", "email": "src@x.com", "password": "Hunter2!secret",
    })
    # The search route writes search_history + emits event regardless of
    # whether the TMDB upstream call succeeds (the bookkeeping is in a
    # try/finally). Status code is best-effort: 200 if TMDB_API_KEY is set in
    # the test env, otherwise still 200 with empty results.
    r = await api_client.get("/api/search?q=inception")
    assert r.status_code == 200

    async for db in gs():
        history = (await db.execute(select(SearchHistory))).scalars().all()
        assert len(history) >= 1
        assert history[0].query_text == "inception"
        assert history[0].query_hash == hashlib.sha256(b"inception").hexdigest()

        events = (await db.execute(
            select(Event).where(Event.event_type == "search.run")
        )).scalars().all()
        assert len(events) == 1
        assert events[0].payload["query_hash"] == hashlib.sha256(b"inception").hexdigest()
        break
```

(Drop the `.catch = None` line — it was a placeholder.)

- [ ] **Step 2: Run, expect failure**

```bash
venv/bin/python -m pytest tests/api/test_search.py::test_search_inserts_search_history_and_event -v
```

Expected: failure (no SearchHistory rows).

- [ ] **Step 3: Edit `streamload/api/routes/search.py`**

```python
import hashlib
from fastapi import Request
from streamload.api.telemetry import emit as emit_event
from streamload.db.models import SearchHistory


@router.get("", response_model=SearchResponse)
async def search(
    user: CurrentUser,
    db: SessionDep,
    request: Request,
    q: str = Query(min_length=1, max_length=100),
) -> SearchResponse:
    qh = hashlib.sha256(q.encode("utf-8")).hexdigest()

    # Bookkeeping FIRST so it lands even if TMDB call fails.
    db.add(SearchHistory(user_id=user.id, query_text=q, query_hash=qh))
    result_count = 0
    try:
        async with httpx.AsyncClient(timeout=15) as http:
            client = _build_tmdb_client(http)
            items = await client.search_multi(q)
        result_count = len(items)
    except Exception:
        items = []
        log.warning("TMDB search failed for %r", q, exc_info=True)
    finally:
        await emit_event(db, request, user_id=user.id, event_type="search.run",
                         payload={"query_hash": qh, "result_count": result_count})
        await db.commit()

    return SearchResponse(
        query=q,
        results=[
            SearchResult(
                tmdb_id=i.tmdb_id, media_type=i.media_type,
                title=i.title, year=i.year, poster_url=i.poster_url,
            ) for i in items
        ],
    )
```

You'll need `db: SessionDep` in the function signature and `from streamload.api.deps import SessionDep` and `from streamload.utils.logger import get_logger; log = get_logger(__name__)` at the top if not already imported.

- [ ] **Step 4: Run tests, expect green**

```bash
venv/bin/python -m pytest tests/api/test_search.py -v
```

Expected: all pass.

- [ ] **Step 5: Commit**

```bash
git add streamload/api/routes/search.py tests/api/test_search.py
git commit -m "feat(search): persist search_history + emit search.run event"
```

---

## Phase G — Bookkeeping + version bump + final smoke

### Task 24: Update `tests/conftest.py` and `tests/api/conftest.py` truncate lists

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/api/conftest.py`

- [ ] **Step 1: Inspect the current truncate lists**

```bash
grep -n "TRUNCATE\|catalog_sources" tests/conftest.py tests/api/conftest.py
```

- [ ] **Step 2: Edit both files to drop `catalog_sources` from the truncate lists and add the new tables**

In `tests/api/conftest.py`, find the tuple in `_truncate_all`. Change:

```python
# Before
for table in (
    "watch_progress", "favorites", "watchlist",
    "collection_items", "catalog_sources", "tv_episodes",
    "intro_markers",
    "catalog_items", "collections",
    "email_tokens", "webauthn_credentials", "sessions",
    "users",
):

# After
for table in (
    "events",
    "search_history", "watch_history",
    "user_settings",
    "watch_progress", "favorites", "watchlist",
    "collection_items", "tv_episodes",
    "intro_markers",
    "catalog_items", "collections",
    "email_tokens", "webauthn_credentials", "sessions",
    "users",
):
```

Apply the same diff to any other conftest.py that has a truncate list.

- [ ] **Step 3: Verify by running the full suite (this is the big one)**

```bash
venv/bin/python -m pytest 2>&1 | tail -10
```

Expected: all tests pass. Number of tests should be lower than the 313 baseline (we deleted ~30+ tests for v1 modules) but with new tests added on top.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/api/conftest.py
git commit -m "test: align truncate lists with v3 schema (drop catalog_sources, add new tables)"
```

---

### Task 25: Bump backend version to 0.3.0

**Files:**
- Modify: `streamload/version.py`

- [ ] **Step 1: Edit version**

```python
__version__ = "0.3.0"
__app_name__ = "Streamload"
__author__ = "alfanowski"
__repo__ = "alfanowski/Streamload"
```

- [ ] **Step 2: Commit**

```bash
git add streamload/version.py
git commit -m "chore: bump version to v0.3.0 (v3 backend)"
```

---

### Task 26: Final smoke test — boot server, hit health, hit a known title, hit settings

**Files:** none modified (smoke only).

- [ ] **Step 1: Apply migrations to a fresh-ish DB**

```bash
set -a; source .env; set +a
venv/bin/alembic upgrade head
```

Expected: succeeds.

- [ ] **Step 2: Boot the API**

```bash
pkill -9 -f granian 2>/dev/null
sleep 1
nohup venv/bin/python streamload.py --api > /tmp/streamload-api.log 2>&1 &
disown
sleep 5
```

- [ ] **Step 3: Verify health + login + a write**

```bash
curl -s http://127.0.0.1:8000/api/health
echo
curl -s -c /tmp/cookies.txt -X POST http://127.0.0.1:8000/api/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alfanowski","password":"Test12345Test"}' | head -c 200
echo
curl -s -i -b /tmp/cookies.txt -X POST "http://127.0.0.1:8000/api/play/1" 2>&1 | head -5
echo
curl -s -b /tmp/cookies.txt http://127.0.0.1:8000/api/settings
echo
curl -s -b /tmp/cookies.txt -X PUT http://127.0.0.1:8000/api/settings \
  -H 'Content-Type: application/json' \
  -d '{"audio_pref_lang":"eng","subs_pref_lang":"ita","autoplay_next_episode":true,"skip_intro":true,"theme":"dark","locale":"it-IT","quality_cap_height":1080}'
```

Expected:
- `/api/health` → 200 with `{"status":"ok","version":"0.3.0"}`.
- Login → 200 with user JSON (admin, role=admin).
- `/api/play/1` → 404 (route is gone, this is the deliberate v2-frontend signal).
- `/api/settings` GET → 200 with default JSON.
- `/api/settings` PUT → 200 echoing the payload.

- [ ] **Step 4: Verify telemetry was captured**

```bash
venv/bin/python -c "
import asyncio, os, asyncpg
async def main():
    url = os.environ['DATABASE_URL'].replace('postgresql+asyncpg://', 'postgresql://')
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(\"SELECT event_type, COUNT(*) FROM events GROUP BY event_type ORDER BY 1\")
    for r in rows: print(dict(r))
    await conn.close()
asyncio.run(main())
"
```

Expected: at least `auth.login_success` (count ≥ 1) shows up.

- [ ] **Step 5: Stop the dev server**

```bash
pkill -9 -f granian 2>/dev/null
```

- [ ] **Step 6: Final commit (no code change, just confirmation)**

```bash
git status
# Should be clean.
```

If clean, no commit needed. If something changed (e.g. a stray __pycache__ entry), discard those changes.

---

## Plan complete

After Task 26 you will have:

- A backend that knows nothing about scraping or upstream services.
- A schema with the four new v3 tables (`user_settings`, `watch_history`, `search_history`, `events`) and without `catalog_sources` or `last_source`.
- Three new endpoints (`GET /next-up/{tmdb_id}?…`, `POST /events`, real `/settings` GET/PUT) plus telemetry baked into auth/favorites/watchlist/passkey/search.
- A test suite that's green end-to-end.
- Backend version `v0.3.0`, ready to deploy to the existing VPS.

The v2 web frontend will start hitting 404 for `/api/play/*` and `/stream/*` once this lands — that's the deliberate prompt to switch to the v3 desktop client (built in Sub-plan #3 onwards).
