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
