"""ORM models — all platform tables."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _uuid() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


# ── Projects (UI grouping only) ────────────────────────────────


class Project(Base):
    __tablename__ = "projects"

    project_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Procedures ──────────────────────────────────────────────────


class Procedure(Base):
    __tablename__ = "procedures"
    __table_args__ = (UniqueConstraint("procedure_id", "version"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    procedure_id: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    version: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="draft")
    effective_date: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False, default="")
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    ckp_json: Mapped[str] = mapped_column(Text, nullable=False)  # JSON stored as TEXT
    provenance_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # provenance block
    retrieval_metadata_json: Mapped[str | None] = mapped_column(Text, nullable=True)  # retrieval_metadata block
    project_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("projects.project_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Runs ────────────────────────────────────────────────────────


class Run(Base):
    __tablename__ = "runs"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    procedure_id: Mapped[str] = mapped_column(String(256), nullable=False)
    procedure_version: Mapped[str] = mapped_column(String(64), nullable=False)
    thread_id: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), default="created")
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    input_vars_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_node_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    last_step_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    parent_run_id: Mapped[str | None] = mapped_column(String(64), nullable=True)  # set for sub-procedure child runs
    project_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("projects.project_id"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    events: Mapped[list[RunEvent]] = relationship(back_populates="run", lazy="selectin")


# ── Run events (append-only timeline) ──────────────────────────


class RunEvent(Base):
    __tablename__ = "run_events"

    event_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.run_id"), nullable=False, index=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    attempt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    run: Mapped[Run] = relationship(back_populates="events")


# ── Approvals ───────────────────────────────────────────────────


class Approval(Base):
    __tablename__ = "approvals"

    approval_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.run_id"), nullable=False, index=True)
    node_id: Mapped[str] = mapped_column(String(256), nullable=False)
    prompt: Mapped[str] = mapped_column(Text, nullable=False)
    decision_type: Mapped[str] = mapped_column(String(64), nullable=False)
    options_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_data_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending")
    decided_by: Mapped[str | None] = mapped_column(String(256), nullable=True)
    decision_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── Step idempotency ────────────────────────────────────────────


class StepIdempotency(Base):
    __tablename__ = "step_idempotency"

    run_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    node_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    step_id: Mapped[str] = mapped_column(String(256), primary_key=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="started")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Artifacts ───────────────────────────────────────────────────


class Artifact(Base):
    __tablename__ = "artifacts"

    artifact_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.run_id"), nullable=False, index=True)
    node_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    uri: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Agent instances ─────────────────────────────────────────────


class AgentInstance(Base):
    __tablename__ = "agent_instances"

    agent_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    channel: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    capabilities: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="online")
    concurrency_limit: Mapped[int] = mapped_column(Integer, default=1)
    resource_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)


# ── Resource leases ─────────────────────────────────────────────


class ResourceLease(Base):
    __tablename__ = "resource_leases"

    lease_id: Mapped[str] = mapped_column(String(64), primary_key=True, default=_uuid)
    resource_key: Mapped[str] = mapped_column(String(256), nullable=False, index=True)
    run_id: Mapped[str] = mapped_column(String(64), ForeignKey("runs.run_id"), nullable=False)
    node_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    step_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    acquired_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
