"""Add procedure release-governance metadata and indexes.

Revision ID: v010_procedure_release_governance
Revises: v009_case_webhook_deliveries_indexes
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v010_procedure_release_governance"
down_revision: Union[str, None] = "v009_case_webhook_deliveries_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def _get_index_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("procedures"):
        return

    with op.batch_alter_table("procedures", schema=None) as batch_op:
        if not _has_column(inspector, "procedures", "release_channel"):
            batch_op.add_column(sa.Column("release_channel", sa.String(length=16), nullable=True))
        if not _has_column(inspector, "procedures", "promoted_from_version"):
            batch_op.add_column(sa.Column("promoted_from_version", sa.String(length=64), nullable=True))
        if not _has_column(inspector, "procedures", "promoted_at"):
            batch_op.add_column(sa.Column("promoted_at", sa.DateTime(timezone=True), nullable=True))
        if not _has_column(inspector, "procedures", "promoted_by"):
            batch_op.add_column(sa.Column("promoted_by", sa.String(length=256), nullable=True))

    index_names = _get_index_names(inspector, "procedures")
    if "ix_procedures_release_channel" not in index_names:
        op.create_index(
            "ix_procedures_release_channel",
            "procedures",
            ["release_channel"],
            unique=False,
        )
    if "ix_procedures_proc_release_channel" not in index_names:
        op.create_index(
            "ix_procedures_proc_release_channel",
            "procedures",
            ["procedure_id", "release_channel"],
            unique=False,
        )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("procedures"):
        return

    index_names = _get_index_names(inspector, "procedures")
    if "ix_procedures_proc_release_channel" in index_names:
        op.drop_index("ix_procedures_proc_release_channel", table_name="procedures")
    if "ix_procedures_release_channel" in index_names:
        op.drop_index("ix_procedures_release_channel", table_name="procedures")

    inspector = sa.inspect(bind)
    columns = {c["name"] for c in inspector.get_columns("procedures")}
    with op.batch_alter_table("procedures", schema=None) as batch_op:
        if "promoted_by" in columns:
            batch_op.drop_column("promoted_by")
        if "promoted_at" in columns:
            batch_op.drop_column("promoted_at")
        if "promoted_from_version" in columns:
            batch_op.drop_column("promoted_from_version")
        if "release_channel" in columns:
            batch_op.drop_column("release_channel")
