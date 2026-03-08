"""Add case webhook subscription table.

Revision ID: v007_case_webhooks
Revises: v006_case_sla
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v007_case_webhooks"
down_revision: Union[str, None] = "v006_case_sla"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "case_webhook_subscriptions",
        sa.Column("subscription_id", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("target_url", sa.Text(), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("secret_env_var", sa.String(length=256), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("subscription_id"),
    )
    op.create_index(
        "ix_case_webhook_subscriptions_event_type",
        "case_webhook_subscriptions",
        ["event_type"],
        unique=False,
    )
    op.create_index(
        "ix_case_webhook_subscriptions_project_id",
        "case_webhook_subscriptions",
        ["project_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_case_webhook_subscriptions_project_id",
        table_name="case_webhook_subscriptions",
    )
    op.drop_index(
        "ix_case_webhook_subscriptions_event_type",
        table_name="case_webhook_subscriptions",
    )
    op.drop_table("case_webhook_subscriptions")
