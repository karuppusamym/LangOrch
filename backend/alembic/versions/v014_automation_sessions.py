"""Add automation_sessions table for durable agent session state.

Revision ID: v014_automation_sessions
Revises: v013_system_settings
Create Date: 2026-04-05
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v014_automation_sessions"
down_revision: Union[str, None] = "v013_system_settings"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("automation_sessions"):
        return

    op.create_table(
        "automation_sessions",
        sa.Column("session_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column("agent_id", sa.String(64), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("tenant_id", sa.String(128), nullable=True),
        sa.Column("user_id", sa.String(256), nullable=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("runs.run_id"), nullable=True),
        sa.Column("data_json", sa.Text(), nullable=False, server_default=sa.text("'{}'")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), server_default=sa.text("CURRENT_TIMESTAMP"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_automation_sessions_agent_id", "automation_sessions", ["agent_id"])
    op.create_index("ix_automation_sessions_channel", "automation_sessions", ["channel"])
    op.create_index("ix_automation_sessions_run_id", "automation_sessions", ["run_id"])
    op.create_index("ix_automation_sessions_tenant_id", "automation_sessions", ["tenant_id"])
    op.create_index("ix_automation_sessions_agent_expires", "automation_sessions", ["agent_id", "expires_at"])
    op.create_index("ix_automation_sessions_channel_expires", "automation_sessions", ["channel", "expires_at"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if inspector.has_table("automation_sessions"):
        op.drop_index("ix_automation_sessions_channel_expires", table_name="automation_sessions")
        op.drop_index("ix_automation_sessions_agent_expires", table_name="automation_sessions")
        op.drop_index("ix_automation_sessions_tenant_id", table_name="automation_sessions")
        op.drop_index("ix_automation_sessions_run_id", table_name="automation_sessions")
        op.drop_index("ix_automation_sessions_channel", table_name="automation_sessions")
        op.drop_index("ix_automation_sessions_agent_id", table_name="automation_sessions")
        op.drop_table("automation_sessions")
