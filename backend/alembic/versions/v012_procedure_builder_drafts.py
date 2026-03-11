"""Add persisted Builder V2 draft storage for procedures.

Revision ID: v012_procedure_builder_drafts
Revises: v011_trigger_dedupe_uniqueness
Create Date: 2026-03-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v012_procedure_builder_drafts"
down_revision: Union[str, None] = "v011_trigger_dedupe_uniqueness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _has_column(inspector: sa.Inspector, table: str, column: str) -> bool:
    return any(c["name"] == column for c in inspector.get_columns(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("procedures"):
        return

    with op.batch_alter_table("procedures", schema=None) as batch_op:
        if not _has_column(inspector, "procedures", "builder_draft_json"):
            batch_op.add_column(sa.Column("builder_draft_json", sa.Text(), nullable=True))
        if not _has_column(inspector, "procedures", "builder_draft_updated_at"):
            batch_op.add_column(sa.Column("builder_draft_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("procedures"):
        return

    columns = {c["name"] for c in inspector.get_columns("procedures")}
    with op.batch_alter_table("procedures", schema=None) as batch_op:
        if "builder_draft_updated_at" in columns:
            batch_op.drop_column("builder_draft_updated_at")
        if "builder_draft_json" in columns:
            batch_op.drop_column("builder_draft_json")