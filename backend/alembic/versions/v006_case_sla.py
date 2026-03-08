"""Add case SLA columns and index.

Revision ID: v006_case_sla
Revises: v005_cases
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v006_case_sla"
down_revision: Union[str, None] = "v005_cases"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sla_due_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("sla_breached_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_cases_sla_due_status", "cases", ["sla_due_at", "status"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_cases_sla_due_status", table_name="cases")

    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_column("sla_breached_at")
        batch_op.drop_column("sla_due_at")
