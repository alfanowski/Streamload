"""user_disabled

Revision ID: a8e2c3d10001
Revises: f4bac1844b73
Create Date: 2026-05-09 16:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a8e2c3d10001"
down_revision: Union[str, Sequence[str], None] = "f4bac1844b73"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("disabled_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "disabled_at")
