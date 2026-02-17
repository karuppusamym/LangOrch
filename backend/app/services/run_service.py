"""Run lifecycle service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, Artifact, ResourceLease, Run, RunEvent, StepIdempotency


async def create_run(
    db: AsyncSession,
    procedure_id: str,
    procedure_version: str,
    input_vars: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> Run:
    run = Run(
        procedure_id=procedure_id,
        procedure_version=procedure_version,
        thread_id="",  # will be set to run_id after flush
        input_vars_json=json.dumps(input_vars) if input_vars else None,
        project_id=project_id,
        status="created",
    )
    db.add(run)
    await db.flush()
    # thread_id defaults to run_id
    run.thread_id = run.run_id
    await db.flush()
    await db.refresh(run)

    # Emit creation event
    await emit_event(db, run.run_id, "run_created")
    return run


async def list_runs(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    order: str = "desc",
) -> list[Run]:
    stmt = select(Run)
    if project_id:
        stmt = stmt.where(Run.project_id == project_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if created_from:
        stmt = stmt.where(Run.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Run.created_at <= created_to)

    stmt = stmt.order_by(Run.created_at.asc() if order == "asc" else Run.created_at.desc())

    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_run(db: AsyncSession, run_id: str) -> Run | None:
    return await db.get(Run, run_id)


async def update_run_status(db: AsyncSession, run_id: str, status: str, **kwargs: Any) -> Run | None:
    run = await db.get(Run, run_id)
    if not run:
        return None
    run.status = status
    if status == "running" and not run.started_at:
        run.started_at = datetime.now(timezone.utc)
    if status in ("succeeded", "completed", "failed", "canceled"):
        run.ended_at = datetime.now(timezone.utc)
    for k, v in kwargs.items():
        if hasattr(run, k):
            setattr(run, k, v)
    await db.flush()
    await db.refresh(run)
    return run


async def prepare_retry(db: AsyncSession, run_id: str) -> Run | None:
    """Prepare an existing run for checkpoint-aware retry execution."""
    run = await db.get(Run, run_id)
    if not run:
        return None

    run.status = "created"
    run.ended_at = None
    run.last_step_id = None
    if not run.thread_id:
        run.thread_id = run.run_id

    await emit_event(
        db,
        run_id,
        "run_retry_requested",
        payload={"thread_id": run.thread_id},
    )

    await db.flush()
    await db.refresh(run)
    return run


async def emit_event(
    db: AsyncSession,
    run_id: str,
    event_type: str,
    node_id: str | None = None,
    step_id: str | None = None,
    attempt: int | None = None,
    payload: dict[str, Any] | None = None,
) -> RunEvent:
    event = RunEvent(
        run_id=run_id,
        event_type=event_type,
        node_id=node_id,
        step_id=step_id,
        attempt=attempt,
        payload_json=json.dumps(payload) if payload else None,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    return event


async def list_events(db: AsyncSession, run_id: str) -> list[RunEvent]:
    stmt = select(RunEvent).where(RunEvent.run_id == run_id).order_by(RunEvent.ts.asc())
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_artifact(
    db: AsyncSession,
    run_id: str,
    kind: str,
    uri: str,
    node_id: str | None = None,
    step_id: str | None = None,
) -> Artifact:
    artifact = Artifact(
        run_id=run_id,
        node_id=node_id,
        step_id=step_id,
        kind=kind,
        uri=uri,
    )
    db.add(artifact)
    await db.flush()
    await db.refresh(artifact)
    return artifact


async def list_artifacts(db: AsyncSession, run_id: str) -> list[Artifact]:
    stmt = (
        select(Artifact)
        .where(Artifact.run_id == run_id)
        .order_by(Artifact.created_at.asc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def delete_run(db: AsyncSession, run_id: str) -> bool:
    run = await db.get(Run, run_id)
    if not run:
        return False

    await db.execute(delete(RunEvent).where(RunEvent.run_id == run_id))
    await db.execute(delete(Approval).where(Approval.run_id == run_id))
    await db.execute(delete(Artifact).where(Artifact.run_id == run_id))
    await db.execute(delete(ResourceLease).where(ResourceLease.run_id == run_id))
    await db.execute(delete(StepIdempotency).where(StepIdempotency.run_id == run_id))
    await db.delete(run)
    await db.flush()
    return True


async def cleanup_runs_before(
    db: AsyncSession,
    before: datetime,
    status: str | None = None,
) -> int:
    stmt = select(Run.run_id).where(Run.created_at < before)
    if status:
        stmt = stmt.where(Run.status == status)

    result = await db.execute(stmt)
    run_ids = [row[0] for row in result.all()]
    if not run_ids:
        return 0

    await db.execute(delete(RunEvent).where(RunEvent.run_id.in_(run_ids)))
    await db.execute(delete(Approval).where(Approval.run_id.in_(run_ids)))
    await db.execute(delete(Artifact).where(Artifact.run_id.in_(run_ids)))
    await db.execute(delete(ResourceLease).where(ResourceLease.run_id.in_(run_ids)))
    await db.execute(delete(StepIdempotency).where(StepIdempotency.run_id.in_(run_ids)))
    await db.execute(delete(Run).where(Run.run_id.in_(run_ids)))
    await db.flush()
    return len(run_ids)
