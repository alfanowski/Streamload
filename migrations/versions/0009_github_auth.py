"""github auth + profile fields

Revision ID: 0009_github_auth
Revises: d2c3e4f50004
Create Date: 2026-05-10
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_github_auth"
down_revision = "d2c3e4f50004"
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
                    existing_type=sa.Text(),
                    nullable=True)


def downgrade() -> None:
    op.alter_column("users", "password_hash",
                    existing_type=sa.Text(),
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
