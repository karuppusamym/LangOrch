"""Add run listing/filter indexes for scalability.

Revision ID: v002
Revises: v001
Create Date: 2026-02-22 00:00:00.000000
"""

from __future__ import annotations

from typing import Sequence, Union

from alembic import op

revision: str = "v002"
down_revision: Union[str, None] = "v001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("ix_runs_status_created_at", "runs", ["status", "created_at"])
    op.create_index("ix_runs_project_created_at", "runs", ["project_id", "created_at"])
    op.create_index("ix_runs_procedure_created_at", "runs", ["procedure_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_runs_procedure_created_at", table_name="runs")
    op.drop_index("ix_runs_project_created_at", table_name="runs")
    op.drop_index("ix_runs_status_created_at", table_name="runs")
