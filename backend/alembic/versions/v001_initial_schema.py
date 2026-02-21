"""Initial schema — all tables.

Revision ID: v001
Revises:
Create Date: 2026-02-20 00:00:00.000000

This migration creates all platform tables from scratch.  It is designed to
run against both SQLite (dev) and PostgreSQL (production) without changes.

To apply:
    cd backend/
    alembic upgrade head
"""
from __future__ import annotations
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "v001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── projects ────────────────────────────────────────────────────────────
    op.create_table(
        "projects",
        sa.Column("project_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── procedures ──────────────────────────────────────────────────────────
    op.create_table(
        "procedures",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("procedure_id", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="draft"),
        sa.Column("effective_date", sa.String(32), nullable=True),
        sa.Column("name", sa.String(256), nullable=False, server_default=""),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("ckp_json", sa.Text(), nullable=False),
        sa.Column("provenance_json", sa.Text(), nullable=True),
        sa.Column("retrieval_metadata_json", sa.Text(), nullable=True),
        sa.Column("trigger_config_json", sa.Text(), nullable=True),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("projects.project_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("procedure_id", "version", name="uq_procedure_version"),
    )
    op.create_index("ix_procedures_procedure_id", "procedures", ["procedure_id"])

    # ── runs ────────────────────────────────────────────────────────────────
    op.create_table(
        "runs",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("procedure_id", sa.String(256), nullable=False),
        sa.Column("procedure_version", sa.String(64), nullable=False),
        sa.Column("thread_id", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("input_vars_json", sa.Text(), nullable=True),
        sa.Column("output_vars_json", sa.Text(), nullable=True),
        sa.Column("total_prompt_tokens", sa.Integer(), nullable=True),
        sa.Column("total_completion_tokens", sa.Integer(), nullable=True),
        sa.Column("estimated_cost_usd", sa.Float(), nullable=True),
        sa.Column("last_node_id", sa.String(256), nullable=True),
        sa.Column("last_step_id", sa.String(256), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("parent_run_id", sa.String(64), nullable=True),
        sa.Column("trigger_type", sa.String(32), nullable=True),
        sa.Column("triggered_by", sa.String(256), nullable=True),
        sa.Column(
            "cancellation_requested",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "project_id",
            sa.String(64),
            sa.ForeignKey("projects.project_id"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── run_events ──────────────────────────────────────────────────────────
    op.create_table(
        "run_events",
        sa.Column("event_id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            nullable=False,
        ),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("event_type", sa.String(64), nullable=False),
        sa.Column("node_id", sa.String(256), nullable=True),
        sa.Column("step_id", sa.String(256), nullable=True),
        sa.Column("attempt", sa.Integer(), nullable=True),
        sa.Column("payload_json", sa.Text(), nullable=True),
    )
    op.create_index("ix_run_events_run_id", "run_events", ["run_id"])

    # ── approvals ───────────────────────────────────────────────────────────
    op.create_table(
        "approvals",
        sa.Column("approval_id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(256), nullable=False),
        sa.Column("prompt", sa.Text(), nullable=False),
        sa.Column("decision_type", sa.String(64), nullable=False),
        sa.Column("options_json", sa.Text(), nullable=True),
        sa.Column("context_data_json", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("decided_by", sa.String(256), nullable=True),
        sa.Column("decision_json", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_approvals_run_id", "approvals", ["run_id"])

    # ── step_idempotency ────────────────────────────────────────────────────
    op.create_table(
        "step_idempotency",
        sa.Column("run_id", sa.String(64), primary_key=True),
        sa.Column("node_id", sa.String(256), primary_key=True),
        sa.Column("step_id", sa.String(256), primary_key=True),
        sa.Column("idempotency_key", sa.String(512), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="started"),
        sa.Column("result_json", sa.Text(), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    # ── artifacts ───────────────────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column("artifact_id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(256), nullable=True),
        sa.Column("step_id", sa.String(256), nullable=True),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("uri", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_artifacts_run_id", "artifacts", ["run_id"])

    # ── agent_instances ─────────────────────────────────────────────────────
    op.create_table(
        "agent_instances",
        sa.Column("agent_id", sa.String(64), primary_key=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("channel", sa.String(64), nullable=False),
        sa.Column("base_url", sa.Text(), nullable=False),
        sa.Column("capabilities", sa.Text(), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="online"),
        sa.Column("concurrency_limit", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("resource_key", sa.String(256), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("circuit_open_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_instances_channel", "agent_instances", ["channel"])
    op.create_index("ix_agent_instances_resource_key", "agent_instances", ["resource_key"])

    # ── resource_leases ─────────────────────────────────────────────────────
    op.create_table(
        "resource_leases",
        sa.Column("lease_id", sa.String(64), primary_key=True),
        sa.Column("resource_key", sa.String(256), nullable=False),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            nullable=False,
        ),
        sa.Column("node_id", sa.String(256), nullable=True),
        sa.Column("step_id", sa.String(256), nullable=True),
        sa.Column("acquired_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("released_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_resource_leases_resource_key", "resource_leases", ["resource_key"])

    # ── trigger_registrations ───────────────────────────────────────────────
    op.create_table(
        "trigger_registrations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("procedure_id", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("trigger_type", sa.String(32), nullable=False),
        sa.Column("schedule", sa.String(256), nullable=True),
        sa.Column("webhook_secret", sa.String(256), nullable=True),
        sa.Column("event_source", sa.String(256), nullable=True),
        sa.Column("dedupe_window_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_concurrent_runs", sa.Integer(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint(
            "procedure_id", "version", name="uq_trigger_procedure_version"
        ),
    )
    op.create_index(
        "ix_trigger_registrations_procedure_id",
        "trigger_registrations",
        ["procedure_id"],
    )

    # ── trigger_dedupe_records ──────────────────────────────────────────────
    op.create_table(
        "trigger_dedupe_records",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("procedure_id", sa.String(256), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column("run_id", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_trigger_dedupe_records_procedure_id",
        "trigger_dedupe_records",
        ["procedure_id"],
    )
    op.create_index(
        "ix_trigger_dedupe_records_payload_hash",
        "trigger_dedupe_records",
        ["payload_hash"],
    )

    # ── run_jobs (durable worker queue) ────────────────────────────────────
    op.create_table(
        "run_jobs",
        sa.Column("job_id", sa.String(64), primary_key=True),
        sa.Column(
            "run_id",
            sa.String(64),
            sa.ForeignKey("runs.run_id"),
            nullable=False,
            unique=True,
        ),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_by", sa.String(256), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_run_jobs_run_id", "run_jobs", ["run_id"])
    # Composite index for efficient worker poll query
    op.create_index("ix_run_jobs_poll", "run_jobs", ["status", "available_at", "priority"])


def downgrade() -> None:
    # Drop in reverse FK order
    op.drop_table("run_jobs")
    op.drop_table("trigger_dedupe_records")
    op.drop_table("trigger_registrations")
    op.drop_table("resource_leases")
    op.drop_table("agent_instances")
    op.drop_table("artifacts")
    op.drop_table("step_idempotency")
    op.drop_table("approvals")
    op.drop_table("run_events")
    op.drop_table("runs")
    op.drop_table("procedures")
    op.drop_table("projects")
