"""composite (tmdb_id, media_type) primary key across catalog tables

Revision ID: f0a1b2c30003
Revises: c91ad5e20002
Create Date: 2026-05-09 19:30:00.000000

TMDB allocates ids in separate namespaces for movies and TV series, so the
same numeric id can map to two different titles (e.g. id 1396 = "Lo specchio"
movie + "Breaking Bad" tv). The pre-0007 schema used the bare tmdb_id as
PK on catalog_items, allowing only one of the two to live in cache.

This migration:
  - Promotes (tmdb_id, media_type) to the composite PK on catalog_items.
  - Adds media_type to every FK table and rebuilds PK + FK to include it.
  - tv_episodes / intro_markers add a CHECK constraint forcing media_type='tv'
    (those tables only make sense for series).
  - User-state tables (watch_progress, favorites, watchlist) gain media_type
    in their PK so the same id can be tracked separately as a movie vs tv.

The backfill assumes existing user-state rows refer to whatever was in
catalog_items at the time, so we copy media_type across via the FK join.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f0a1b2c30003"
down_revision: Union[str, Sequence[str], None] = "c91ad5e20002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Tables that link to catalog_items via tmdb_id. (table, fk_constraint_name)
DEPENDENT_TABLES = [
    ("catalog_sources", "catalog_sources_tmdb_id_fkey"),
    ("collection_items", "collection_items_tmdb_id_fkey"),
    ("tv_episodes", "tv_episodes_tmdb_id_fkey"),
    ("watch_progress", "watch_progress_tmdb_id_fkey"),
    ("favorites", "favorites_tmdb_id_fkey"),
    ("watchlist", "watchlist_tmdb_id_fkey"),
    ("intro_markers", "intro_markers_tmdb_id_fkey"),
]


def upgrade() -> None:
    # ── 1. Add media_type to all dependent tables, NULLABLE first for backfill.
    for table, _ in DEPENDENT_TABLES:
        op.add_column(table, sa.Column("media_type", sa.Text(), nullable=True))

    # ── 2. Backfill media_type from catalog_items via the existing FK.
    for table, _ in DEPENDENT_TABLES:
        op.execute(f"""
            UPDATE {table} t
            SET media_type = ci.media_type
            FROM catalog_items ci
            WHERE ci.tmdb_id = t.tmdb_id
        """)

    # tv_episodes + intro_markers conceptually only exist for tv; force the
    # value if any row was ingested without a backing catalog_items row.
    op.execute("UPDATE tv_episodes SET media_type = 'tv' WHERE media_type IS NULL")
    op.execute("UPDATE intro_markers SET media_type = 'tv' WHERE media_type IS NULL")

    # Other tables may have orphan rows (no catalog_items match). Drop them so
    # NOT NULL + new FK can be created cleanly.
    for table, _ in DEPENDENT_TABLES:
        if table in ("tv_episodes", "intro_markers"):
            continue
        op.execute(f"DELETE FROM {table} WHERE media_type IS NULL")

    for table, _ in DEPENDENT_TABLES:
        op.alter_column(table, "media_type", nullable=False)

    # ── 3. Drop old FKs and the old PK on catalog_items.
    for table, fk_name in DEPENDENT_TABLES:
        op.drop_constraint(fk_name, table, type_="foreignkey")

    op.drop_constraint("catalog_items_pkey", "catalog_items", type_="primary")
    op.create_primary_key(
        "catalog_items_pkey", "catalog_items", ["tmdb_id", "media_type"],
    )

    # ── 4. Rebuild dependent PKs to include media_type, recreate FKs.

    # catalog_sources: PK was (tmdb_id, service_short_name) → add media_type.
    op.drop_constraint("catalog_sources_pkey", "catalog_sources", type_="primary")
    op.create_primary_key(
        "catalog_sources_pkey", "catalog_sources",
        ["tmdb_id", "media_type", "service_short_name"],
    )
    op.create_foreign_key(
        "catalog_sources_tmdb_id_fkey", "catalog_sources", "catalog_items",
        ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
        ondelete="CASCADE",
    )

    # collection_items: PK was (collection_id, tmdb_id) → add media_type.
    op.drop_constraint("collection_items_pkey", "collection_items", type_="primary")
    op.create_primary_key(
        "collection_items_pkey", "collection_items",
        ["collection_id", "tmdb_id", "media_type"],
    )
    op.create_foreign_key(
        "collection_items_tmdb_id_fkey", "collection_items", "catalog_items",
        ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
        ondelete="CASCADE",
    )

    # tv_episodes: PK was (tmdb_id, season_number, episode_number); media_type
    # is implied 'tv' but FK still needs both columns.
    op.drop_constraint("tv_episodes_pkey", "tv_episodes", type_="primary")
    op.create_primary_key(
        "tv_episodes_pkey", "tv_episodes",
        ["tmdb_id", "media_type", "season_number", "episode_number"],
    )
    op.create_check_constraint(
        "ck_tv_episodes_media_type", "tv_episodes", "media_type = 'tv'",
    )
    op.create_foreign_key(
        "tv_episodes_tmdb_id_fkey", "tv_episodes", "catalog_items",
        ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
        ondelete="CASCADE",
    )

    # intro_markers: same shape.
    op.drop_constraint("intro_markers_pkey", "intro_markers", type_="primary")
    op.create_primary_key(
        "intro_markers_pkey", "intro_markers",
        ["tmdb_id", "media_type", "season_number"],
    )
    op.create_check_constraint(
        "ck_intro_markers_media_type", "intro_markers", "media_type = 'tv'",
    )
    op.create_foreign_key(
        "intro_markers_tmdb_id_fkey", "intro_markers", "catalog_items",
        ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
        ondelete="CASCADE",
    )

    # watch_progress: PK was (user_id, tmdb_id, season, episode). Add media_type.
    op.drop_constraint("watch_progress_pkey", "watch_progress", type_="primary")
    op.create_primary_key(
        "watch_progress_pkey", "watch_progress",
        ["user_id", "tmdb_id", "media_type", "season_number", "episode_number"],
    )
    op.create_foreign_key(
        "watch_progress_tmdb_id_fkey", "watch_progress", "catalog_items",
        ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
        ondelete="CASCADE",
    )

    # favorites + watchlist: PK was (user_id, tmdb_id). Add media_type.
    for table in ("favorites", "watchlist"):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(
            f"{table}_pkey", table, ["user_id", "tmdb_id", "media_type"],
        )
        op.create_foreign_key(
            f"{table}_tmdb_id_fkey", table, "catalog_items",
            ["tmdb_id", "media_type"], ["tmdb_id", "media_type"],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    # Reverse the FK + PK rebuilds. Doesn't drop the media_type columns to
    # preserve data — re-applying upgrade() is idempotent on the columns.
    for table, fk_name in DEPENDENT_TABLES:
        op.drop_constraint(fk_name, table, type_="foreignkey")

    op.drop_constraint("catalog_items_pkey", "catalog_items", type_="primary")
    op.create_primary_key("catalog_items_pkey", "catalog_items", ["tmdb_id"])

    op.drop_constraint("catalog_sources_pkey", "catalog_sources", type_="primary")
    op.create_primary_key(
        "catalog_sources_pkey", "catalog_sources",
        ["tmdb_id", "service_short_name"],
    )
    op.create_foreign_key(
        "catalog_sources_tmdb_id_fkey", "catalog_sources", "catalog_items",
        ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
    )

    op.drop_constraint("collection_items_pkey", "collection_items", type_="primary")
    op.create_primary_key(
        "collection_items_pkey", "collection_items", ["collection_id", "tmdb_id"],
    )
    op.create_foreign_key(
        "collection_items_tmdb_id_fkey", "collection_items", "catalog_items",
        ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
    )

    op.drop_constraint("ck_tv_episodes_media_type", "tv_episodes", type_="check")
    op.drop_constraint("tv_episodes_pkey", "tv_episodes", type_="primary")
    op.create_primary_key(
        "tv_episodes_pkey", "tv_episodes",
        ["tmdb_id", "season_number", "episode_number"],
    )
    op.create_foreign_key(
        "tv_episodes_tmdb_id_fkey", "tv_episodes", "catalog_items",
        ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
    )

    op.drop_constraint("ck_intro_markers_media_type", "intro_markers", type_="check")
    op.drop_constraint("intro_markers_pkey", "intro_markers", type_="primary")
    op.create_primary_key(
        "intro_markers_pkey", "intro_markers", ["tmdb_id", "season_number"],
    )
    op.create_foreign_key(
        "intro_markers_tmdb_id_fkey", "intro_markers", "catalog_items",
        ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
    )

    op.drop_constraint("watch_progress_pkey", "watch_progress", type_="primary")
    op.create_primary_key(
        "watch_progress_pkey", "watch_progress",
        ["user_id", "tmdb_id", "season_number", "episode_number"],
    )
    op.create_foreign_key(
        "watch_progress_tmdb_id_fkey", "watch_progress", "catalog_items",
        ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
    )

    for table in ("favorites", "watchlist"):
        op.drop_constraint(f"{table}_pkey", table, type_="primary")
        op.create_primary_key(f"{table}_pkey", table, ["user_id", "tmdb_id"])
        op.create_foreign_key(
            f"{table}_tmdb_id_fkey", table, "catalog_items",
            ["tmdb_id"], ["tmdb_id"], ondelete="CASCADE",
        )
