"""Add users and secret_entries tables.

Revision ID: v004_users_secrets
Revises: v003_agent_pool_id
Create Date: 2026-02-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "v004_users_secrets"
down_revision = "v003_agent_pool_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("user_id", sa.String(64), primary_key=True),
        sa.Column("username", sa.String(128), nullable=False, unique=True),
        sa.Column("email", sa.String(256), nullable=False, unique=True),
        sa.Column("full_name", sa.String(256), nullable=True),
        sa.Column("hashed_password", sa.Text, nullable=False),
        sa.Column("role", sa.String(32), nullable=False, server_default="viewer"),
        sa.Column("is_active", sa.Boolean, nullable=False, server_default=sa.true()),
        sa.Column("sso_subject", sa.String(512), nullable=True, unique=True),
        sa.Column("sso_provider", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_users_username", "users", ["username"], unique=True)
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "secret_entries",
        sa.Column("secret_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False, unique=True),
        sa.Column("encrypted_value", sa.Text, nullable=False),
        sa.Column("description", sa.Text, nullable=True),
        sa.Column("provider_hint", sa.String(32), nullable=False, server_default="db"),
        sa.Column("tags_json", sa.Text, nullable=True),
        sa.Column("created_by", sa.String(256), nullable=True),
        sa.Column("updated_by", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_secret_entries_name", "secret_entries", ["name"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_secret_entries_name", "secret_entries")
    op.drop_table("secret_entries")
    op.drop_index("ix_users_email", "users")
    op.drop_index("ix_users_username", "users")
    op.drop_table("users")
