"""Harden trigger dedupe records with uniqueness.

Revision ID: v011_trigger_dedupe_uniqueness
Revises: v010_procedure_release_governance
Create Date: 2026-03-08
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "v011_trigger_dedupe_uniqueness"
down_revision: Union[str, None] = "v010_procedure_release_governance"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_unique_names(inspector: sa.Inspector, table_name: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table_name) if constraint.get("name")}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("trigger_dedupe_records"):
        return

    dedupe = sa.table(
        "trigger_dedupe_records",
        sa.column("id", sa.Integer),
        sa.column("procedure_id", sa.String),
        sa.column("payload_hash", sa.String),
        sa.column("created_at", sa.DateTime(timezone=True)),
    )

    ranked_duplicates = sa.select(dedupe.c.id).where(
        sa.exists(
            sa.select(sa.literal(1)).where(
                sa.and_(
                    dedupe.c.procedure_id == sa.column("d2_procedure_id"),
                    dedupe.c.payload_hash == sa.column("d2_payload_hash"),
                )
            )
        )
    )

    # Use SQL text for dialect-neutral duplicate cleanup: keep latest created_at/id per pair.
    op.execute(
        sa.text(
            """
            DELETE FROM trigger_dedupe_records
            WHERE id NOT IN (
                SELECT keep_id FROM (
                    SELECT t1.id AS keep_id
                    FROM trigger_dedupe_records t1
                    LEFT JOIN trigger_dedupe_records t2
                      ON t1.procedure_id = t2.procedure_id
                     AND t1.payload_hash = t2.payload_hash
                     AND (
                         t2.created_at > t1.created_at OR
                         (t2.created_at = t1.created_at AND t2.id > t1.id)
                     )
                    WHERE t2.id IS NULL
                ) kept
            )
            """
        )
    )

    inspector = sa.inspect(bind)
    unique_names = _get_unique_names(inspector, "trigger_dedupe_records")
    if "uq_trigger_dedupe_records_procedure_payload" not in unique_names:
        with op.batch_alter_table("trigger_dedupe_records", schema=None) as batch_op:
            batch_op.create_unique_constraint(
                "uq_trigger_dedupe_records_procedure_payload",
                ["procedure_id", "payload_hash"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("trigger_dedupe_records"):
        return

    unique_names = _get_unique_names(inspector, "trigger_dedupe_records")
    if "uq_trigger_dedupe_records_procedure_payload" in unique_names:
        with op.batch_alter_table("trigger_dedupe_records", schema=None) as batch_op:
            batch_op.drop_constraint(
                "uq_trigger_dedupe_records_procedure_payload",
                type_="unique",
            )