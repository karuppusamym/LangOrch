"""Add case type and SLA policy profiles.

Revision ID: v008_case_sla_policies
Revises: v007_case_webhooks
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v008_case_sla_policies"
down_revision: Union[str, None] = "v007_case_webhooks"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.add_column(sa.Column("case_type", sa.String(length=128), nullable=True))

    op.create_index("ix_cases_case_type", "cases", ["case_type"], unique=False)

    op.create_table(
        "case_sla_policies",
        sa.Column("policy_id", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("case_type", sa.String(length=128), nullable=True),
        sa.Column("priority", sa.String(length=32), nullable=True),
        sa.Column("due_minutes", sa.Integer(), nullable=False),
        sa.Column("breach_status", sa.String(length=32), nullable=False, server_default="escalated"),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("policy_id"),
    )
    op.create_index("ix_case_sla_policies_project", "case_sla_policies", ["project_id"], unique=False)
    op.create_index("ix_case_sla_policies_case_type", "case_sla_policies", ["case_type"], unique=False)
    op.create_index("ix_case_sla_policies_priority", "case_sla_policies", ["priority"], unique=False)
    op.create_index("ix_case_sla_policies_enabled", "case_sla_policies", ["enabled"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_case_sla_policies_enabled", table_name="case_sla_policies")
    op.drop_index("ix_case_sla_policies_priority", table_name="case_sla_policies")
    op.drop_index("ix_case_sla_policies_case_type", table_name="case_sla_policies")
    op.drop_index("ix_case_sla_policies_project", table_name="case_sla_policies")
    op.drop_table("case_sla_policies")
    op.drop_index("ix_cases_case_type", table_name="cases")
    with op.batch_alter_table("cases", schema=None) as batch_op:
        batch_op.drop_column("case_type")
