"""Harden webhook delivery schema and DLQ query indexes.

Revision ID: v009_case_webhook_deliveries_indexes
Revises: v008_case_sla_policies
Create Date: 2026-03-07
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v009_case_webhook_deliveries_indexes"
down_revision: Union[str, None] = "v008_case_sla_policies"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _get_index_names(bind: sa.engine.Connection, table_name: str) -> set[str]:
    inspector = sa.inspect(bind)
    return {idx["name"] for idx in inspector.get_indexes(table_name)}


def _create_index_if_missing(name: str, table_name: str, columns: list[str]) -> None:
    bind = op.get_bind()
    if name in _get_index_names(bind, table_name):
        return
    op.create_index(name, table_name, columns, unique=False)


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    if not inspector.has_table("case_webhook_deliveries"):
        op.create_table(
            "case_webhook_deliveries",
            sa.Column("delivery_id", sa.String(length=64), nullable=False),
            sa.Column("subscription_id", sa.String(length=64), nullable=False),
            sa.Column("case_event_id", sa.Integer(), nullable=True),
            sa.Column("case_id", sa.String(length=64), nullable=True),
            sa.Column("project_id", sa.String(length=64), nullable=True),
            sa.Column("event_type", sa.String(length=64), nullable=False),
            sa.Column("payload_json", sa.Text(), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False, server_default="pending"),
            sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
            sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("last_status_code", sa.Integer(), nullable=True),
            sa.Column("last_error", sa.Text(), nullable=True),
            sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
            sa.ForeignKeyConstraint(
                ["subscription_id"], ["case_webhook_subscriptions.subscription_id"]
            ),
            sa.PrimaryKeyConstraint("delivery_id"),
        )

    # Legacy indexes used by existing worker/query paths.
    _create_index_if_missing(
        "ix_case_webhook_deliveries_status_next",
        "case_webhook_deliveries",
        ["status", "next_attempt_at"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_subscription",
        "case_webhook_deliveries",
        ["subscription_id"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_event_type",
        "case_webhook_deliveries",
        ["event_type"],
    )

    # New indexes for DLQ list/count operator flows.
    _create_index_if_missing(
        "ix_case_webhook_deliveries_status_created_at",
        "case_webhook_deliveries",
        ["status", "created_at"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_status_updated_at",
        "case_webhook_deliveries",
        ["status", "updated_at"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_status_attempts",
        "case_webhook_deliveries",
        ["status", "attempts"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_case_status_created_at",
        "case_webhook_deliveries",
        ["case_id", "status", "created_at"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_subscription_status_created_at",
        "case_webhook_deliveries",
        ["subscription_id", "status", "created_at"],
    )
    _create_index_if_missing(
        "ix_case_webhook_deliveries_event_status_created_at",
        "case_webhook_deliveries",
        ["event_type", "status", "created_at"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if not inspector.has_table("case_webhook_deliveries"):
        return

    for idx_name in [
        "ix_case_webhook_deliveries_event_status_created_at",
        "ix_case_webhook_deliveries_subscription_status_created_at",
        "ix_case_webhook_deliveries_case_status_created_at",
        "ix_case_webhook_deliveries_status_attempts",
        "ix_case_webhook_deliveries_status_updated_at",
        "ix_case_webhook_deliveries_status_created_at",
    ]:
        if idx_name in _get_index_names(bind, "case_webhook_deliveries"):
            op.drop_index(idx_name, table_name="case_webhook_deliveries")
