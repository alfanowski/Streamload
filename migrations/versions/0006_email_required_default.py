"""email_required defaults to false

Revision ID: c91ad5e20002
Revises: a8e2c3d10001
Create Date: 2026-05-09 16:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = "c91ad5e20002"
down_revision: Union[str, Sequence[str], None] = "a8e2c3d10001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("users", "email_required", server_default="false")


def downgrade() -> None:
    op.alter_column("users", "email_required", server_default="true")
