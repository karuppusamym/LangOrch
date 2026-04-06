"""batch jobs, case procedure policies, and trigger dispatch metadata

Revision ID: v015_batch_jobs_and_case_policies
Revises: v014_automation_sessions
Create Date: 2026-04-05
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "v015_batch_jobs_and_case_policies"
down_revision = "v014_automation_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "case_procedure_policies",
        sa.Column("policy_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("case_type", sa.String(length=128), nullable=False),
        sa.Column("procedure_id", sa.String(length=256), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
        sa.UniqueConstraint("project_id", "case_type", "procedure_id", name="uq_case_proc_policy_scope"),
    )
    op.create_index("ix_case_proc_policies_scope", "case_procedure_policies", ["project_id", "case_type"])
    op.create_index("ix_case_proc_policies_procedure", "case_procedure_policies", ["procedure_id"])
    op.create_index("ix_case_proc_policies_enabled", "case_procedure_policies", ["enabled"])

    op.create_table(
        "batch_jobs",
        sa.Column("batch_job_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("procedure_id", sa.String(length=256), nullable=False),
        sa.Column("procedure_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("source_format", sa.String(length=32), nullable=False, server_default="json"),
        sa.Column("total_items", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("create_case_per_item", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("case_type", sa.String(length=128), nullable=True),
        sa.Column("trigger_type", sa.String(length=32), nullable=True),
        sa.Column("triggered_by", sa.String(length=256), nullable=True),
        sa.Column("project_id", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["project_id"], ["projects.project_id"]),
    )
    op.create_index("ix_batch_jobs_status_created_at", "batch_jobs", ["status", "created_at"])
    op.create_index("ix_batch_jobs_project_created_at", "batch_jobs", ["project_id", "created_at"])
    op.create_index("ix_batch_jobs_procedure_created_at", "batch_jobs", ["procedure_id", "created_at"])

    op.create_table(
        "batch_job_items",
        sa.Column("item_id", sa.String(length=64), primary_key=True, nullable=False),
        sa.Column("batch_job_id", sa.String(length=64), nullable=False),
        sa.Column("item_index", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False, server_default="queued"),
        sa.Column("input_vars_json", sa.Text(), nullable=True),
        sa.Column("run_id", sa.String(length=64), nullable=True),
        sa.Column("case_id", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["batch_job_id"], ["batch_jobs.batch_job_id"]),
        sa.ForeignKeyConstraint(["run_id"], ["runs.run_id"]),
        sa.ForeignKeyConstraint(["case_id"], ["cases.case_id"]),
        sa.UniqueConstraint("batch_job_id", "item_index", name="uq_batch_job_item_index"),
    )
    op.create_index("ix_batch_job_items_batch_status", "batch_job_items", ["batch_job_id", "status"])
    op.create_index("ix_batch_job_items_run_id", "batch_job_items", ["run_id"])
    op.create_index("ix_batch_job_items_case_id", "batch_job_items", ["case_id"])

    with op.batch_alter_table("runs") as batch_op:
        batch_op.add_column(sa.Column("batch_job_id", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("batch_item_index", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("link_source", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("input_snapshot_source", sa.String(length=64), nullable=True))
    op.create_index("ix_runs_batch_created_at", "runs", ["batch_job_id", "created_at"])

    with op.batch_alter_table("trigger_registrations") as batch_op:
        batch_op.add_column(sa.Column("dispatch_mode", sa.String(length=32), nullable=False, server_default="run"))
        batch_op.add_column(sa.Column("static_payload_json", sa.Text(), nullable=True))
        batch_op.add_column(sa.Column("case_type", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("case_title_template", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("case_external_ref_field", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("create_case_tags_json", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("trigger_registrations") as batch_op:
        batch_op.drop_column("create_case_tags_json")
        batch_op.drop_column("case_external_ref_field")
        batch_op.drop_column("case_title_template")
        batch_op.drop_column("case_type")
        batch_op.drop_column("static_payload_json")
        batch_op.drop_column("dispatch_mode")

    op.drop_index("ix_runs_batch_created_at", table_name="runs")
    with op.batch_alter_table("runs") as batch_op:
        batch_op.drop_column("input_snapshot_source")
        batch_op.drop_column("link_source")
        batch_op.drop_column("batch_item_index")
        batch_op.drop_column("batch_job_id")

    op.drop_index("ix_batch_job_items_case_id", table_name="batch_job_items")
    op.drop_index("ix_batch_job_items_run_id", table_name="batch_job_items")
    op.drop_index("ix_batch_job_items_batch_status", table_name="batch_job_items")
    op.drop_table("batch_job_items")

    op.drop_index("ix_batch_jobs_procedure_created_at", table_name="batch_jobs")
    op.drop_index("ix_batch_jobs_project_created_at", table_name="batch_jobs")
    op.drop_index("ix_batch_jobs_status_created_at", table_name="batch_jobs")
    op.drop_table("batch_jobs")

    op.drop_index("ix_case_proc_policies_enabled", table_name="case_procedure_policies")
    op.drop_index("ix_case_proc_policies_procedure", table_name="case_procedure_policies")
    op.drop_index("ix_case_proc_policies_scope", table_name="case_procedure_policies")
    op.drop_table("case_procedure_policies")

