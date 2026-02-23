"""Add pool_id column to agent_instances for fair round-robin dispatch.

Revision ID: v003
Revises: v002
Create Date: 2026-02-23 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v003"
down_revision: Union[str, None] = "v002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add pool_id — nullable; agents without a pool are treated as standalone
    op.add_column(
        "agent_instances",
        sa.Column("pool_id", sa.String(128), nullable=True),
    )
    # Index speeds up pool-based lookups in _find_capable_agent
    op.create_index("ix_agent_instances_pool_id", "agent_instances", ["pool_id"])


def downgrade() -> None:
    op.drop_index("ix_agent_instances_pool_id", table_name="agent_instances")
    op.drop_column("agent_instances", "pool_id")
