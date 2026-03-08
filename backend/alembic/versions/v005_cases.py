"""Add case-centric tables and run linkage.

Revision ID: v005_cases
Revises: 194a461733a3
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v005_cases"
down_revision: Union[str, None] = "194a461733a3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "cases",
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("external_ref", sa.String(length=256), nullable=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="open"),
        sa.Column("priority", sa.String(length=32), nullable=False, server_default="normal"),
        sa.Column("owner", sa.String(length=256), nullable=True),
        sa.Column("tags_json", sa.Text(), nullable=True),
        sa.Column("metadata_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.PrimaryKeyConstraint("case_id"),
    )
    op.create_index("ix_cases_external_ref", "cases", ["external_ref"], unique=False)
    op.create_index("ix_cases_project_created_at", "cases", ["project_id", "created_at"], unique=False)
    op.create_index("ix_cases_status_created_at", "cases", ["status", "created_at"], unique=False)

    op.create_table(
        "case_events",
        sa.Column("event_id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("case_id", sa.String(length=64), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("actor", sa.String(length=256), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.PrimaryKeyConstraint("event_id"),
    )
    op.create_index("ix_case_events_case_id", "case_events", ["case_id"], unique=False)
    op.create_index("ix_case_events_case_ts", "case_events", ["case_id", "ts"], unique=False)

    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("case_id", sa.String(length=64), nullable=True))
        batch_op.create_foreign_key(
            "fk_runs_case_id_cases",
            "cases",
            ["case_id"],
            ["case_id"],
        )

    op.create_index("ix_runs_case_created_at", "runs", ["case_id", "created_at"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_runs_case_created_at", table_name="runs")
    with op.batch_alter_table("runs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_runs_case_id_cases", type_="foreignkey")
        batch_op.drop_column("case_id")

    op.drop_index("ix_case_events_case_ts", table_name="case_events")
    op.drop_index("ix_case_events_case_id", table_name="case_events")
    op.drop_table("case_events")

    op.drop_index("ix_cases_status_created_at", table_name="cases")
    op.drop_index("ix_cases_project_created_at", table_name="cases")
    op.drop_index("ix_cases_external_ref", table_name="cases")
    op.drop_table("cases")
