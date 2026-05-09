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
