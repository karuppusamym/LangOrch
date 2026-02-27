"""Run lifecycle service."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval, Artifact, ResourceLease, Run, RunEvent, RunJob, StepIdempotency
from app.utils.redaction import redact_sensitive_data, build_patterns


async def create_run(
    db: AsyncSession,
    procedure_id: str,
    procedure_version: str,
    input_vars: dict[str, Any] | None = None,
    project_id: str | None = None,
    trigger_type: str | None = None,
    triggered_by: str | None = None,
) -> Run:
    run = Run(
        procedure_id=procedure_id,
        procedure_version=procedure_version,
        thread_id="",  # will be set to run_id after flush
        input_vars_json=json.dumps(input_vars) if input_vars else None,
        project_id=project_id,
        trigger_type=trigger_type,
        triggered_by=triggered_by,
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
    procedure_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> list[Run]:
    stmt = select(Run)
    if procedure_id:
        stmt = stmt.where(Run.procedure_id == procedure_id)
    if project_id:
        stmt = stmt.where(Run.project_id == project_id)
    if status:
        stmt = stmt.where(Run.status == status)
    if created_from:
        stmt = stmt.where(Run.created_at >= created_from)
    if created_to:
        stmt = stmt.where(Run.created_at <= created_to)

    stmt = stmt.order_by(Run.created_at.asc() if order == "asc" else Run.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)

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
    if status in ("succeeded", "completed", "failed", "canceled", "cancelled"):
        run.ended_at = datetime.now(timezone.utc)
        # Void any pending approvals so the approvals list stays in sync
        await db.execute(
            update(Approval)
            .where(Approval.run_id == run_id, Approval.status == "pending")
            .values(status="cancelled")
        )
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
    run.error_message = None  # clear previous failure reason
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
    extra_redacted_fields: list[str] | None = None,
) -> RunEvent:
    # Redact sensitive fields before persisting
    # Merge default patterns with any extra fields from CKP audit_config
    patterns = build_patterns(extra_redacted_fields) if extra_redacted_fields else None
    sanitized_payload = redact_sensitive_data(payload, extra_patterns=patterns) if payload else None
    
    event = RunEvent(
        run_id=run_id,
        event_type=event_type,
        node_id=node_id,
        step_id=step_id,
        attempt=attempt,
        payload_json=json.dumps(sanitized_payload) if sanitized_payload else None,
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
    name: str | None = None,
    mime_type: str | None = None,
    size_bytes: int | None = None,
) -> Artifact:
    """Persist an artifact record.

    If ``uri`` is a local file path inside ``ARTIFACTS_DIR`` it is converted to
    a ``/api/artifacts/<rel_path>`` URL so browsers can fetch it directly
    (the backend mounts ARTIFACTS_DIR as a StaticFiles handler at that path).
    External http(s) URIs and paths already starting with ``/api/`` are kept
    as-is.
    """
    import os as _os
    from app.config import settings as _settings

    def _normalize(raw_uri: str) -> str:
        if (
            raw_uri.startswith("http://")
            or raw_uri.startswith("https://")
            or raw_uri.startswith("/api/")
        ):
            return raw_uri
        try:
            artifacts_abs = _os.path.abspath(_settings.ARTIFACTS_DIR)
            uri_abs = _os.path.abspath(raw_uri)
            if uri_abs.startswith(artifacts_abs):
                rel = _os.path.relpath(uri_abs, artifacts_abs)
                return "/api/artifacts/" + rel.replace(_os.sep, "/")
        except Exception:
            pass
        return raw_uri

    artifact = Artifact(
        run_id=run_id,
        node_id=node_id,
        step_id=step_id,
        kind=kind,
        uri=_normalize(uri),
        name=name,
        mime_type=mime_type,
        size_bytes=size_bytes,
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
    await db.execute(delete(RunJob).where(RunJob.run_id == run_id))
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
    await db.execute(delete(RunJob).where(RunJob.run_id.in_(run_ids)))
    await db.execute(delete(Run).where(Run.run_id.in_(run_ids)))
    await db.flush()
    return len(run_ids)


async def get_run_diagnostics(db: AsyncSession, run_id: str) -> dict:
    """Gather diagnostic information for a run."""
    run = await db.get(Run, run_id)
    if not run:
        return None

    # Check for retry events
    retry_stmt = (
        select(RunEvent.event_id)
        .where(RunEvent.run_id == run_id)
        .where(RunEvent.event_type == "run_retry_requested")
        .limit(1)
    )
    has_retry = (await db.execute(retry_stmt)).first() is not None

    # Get idempotency entries
    idem_stmt = select(StepIdempotency).where(StepIdempotency.run_id == run_id)
    idem_result = await db.execute(idem_stmt)
    idem_entries = [
        {
            "node_id": row.node_id,
            "step_id": row.step_id,
            "idempotency_key": row.idempotency_key,
            "status": row.status,
            "has_cached_result": row.result_json is not None,
            "updated_at": row.updated_at,
        }
        for row in idem_result.scalars().all()
    ]

    # Get lease information
    lease_stmt = select(ResourceLease).where(
        ResourceLease.run_id == run_id,
        ResourceLease.released_at.is_(None),
    )
    lease_result = await db.execute(lease_stmt)
    lease_entries = [
        {
            "lease_id": row.lease_id,
            "resource_key": row.resource_key,
            "node_id": row.node_id,
            "step_id": row.step_id,
            "acquired_at": row.acquired_at,
            "expires_at": row.expires_at,
            "released_at": row.released_at,
            "is_active": True,
        }
        for row in lease_result.scalars().all()
    ]

    # Event counts
    total_events_stmt = select(func.count()).select_from(RunEvent).where(RunEvent.run_id == run_id)
    total_events = int((await db.execute(total_events_stmt)).scalar() or 0)

    error_events_stmt = (
        select(func.count())
        .select_from(RunEvent)
        .where(RunEvent.run_id == run_id)
        .where(RunEvent.event_type.in_(["error", "run_failed"]))
    )
    error_events = int((await db.execute(error_events_stmt)).scalar() or 0)

    return {
        "run_id": run.run_id,
        "thread_id": run.thread_id,
        "status": run.status,
        "last_node_id": run.last_node_id,
        "last_step_id": run.last_step_id,
        "has_retry_event": has_retry,
        "idempotency_entries": idem_entries,
        "active_leases": lease_entries,
        "total_events": total_events,
        "error_events": error_events,
    }


async def auto_fail_stalled_workflows(db: AsyncSession, timeout_minutes: int) -> list[str]:
    """Find runs that are 'paused' waiting for a workflow callback for too long, and fail them.
    
    A run is considered stalled if its status is 'paused', and it has a 'workflow_delegated'
    event older than the timeout, without any subsequent events indicating resumption.
    """
    from datetime import timedelta
    from app.db.models import Run, RunEvent
    from sqlalchemy.orm import aliased
    import logging

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=timeout_minutes)
    
    # We want to find paused runs where we see a workflow_delegated event older than cutoff
    # Ensure there isn't a newer event (though if it resumed it wouldn't be paused)
    # Finding paused runs is the first filter.
    stmt = (
        select(Run, RunEvent)
        .join(RunEvent, Run.run_id == RunEvent.run_id)
        .where(
            Run.status == "paused",
            RunEvent.event_type == "workflow_delegated",
            RunEvent.ts < cutoff
        )
    )
    result = await db.execute(stmt)
    
    failed_runs = []
    
    # Since a run could have multiple delegations over its lifetime, 
    # we need to be careful. If the run is currently paused, and the *latest*
    # event is workflow_delegated, then it is waiting for a webhook.
    # In SQLite, getting the latest event per run is sometimes tricky using group_by.
    # Instead, we pull the candidates and check their latest event.
    candidates = result.all()
    
    if not candidates:
        return []

    # Map run_id -> (Run, most_recent_workflow_delegated_event)
    run_map = {}
    for r, ev in candidates:
        if r.run_id not in run_map or ev.ts > run_map[r.run_id][1].ts:
            run_map[r.run_id] = (r, ev)
            
    # For each candidate run, fetch its absolute latest event to ensure it is actually workflow_delegated
    for r_id, (run, ev) in run_map.items():
        latest_event_stmt = (
            select(RunEvent.event_type)
            .where(RunEvent.run_id == r_id)
            .order_by(RunEvent.ts.desc())
            .limit(1)
        )
        latest_ev_type = (await db.execute(latest_event_stmt)).scalar()
        
        if latest_ev_type == "workflow_delegated":
            # The run is stuck waiting for a callback! Fail it.
            run.status = "failed"
            run.error_message = f"Workflow webhook callback timed out after {timeout_minutes} minutes."
            run.ended_at = datetime.now(timezone.utc)
            
            # Emit failure event
            await emit_event(
                db, 
                r_id, 
                "run_failed", 
                payload={"error": run.error_message, "timeout_minutes": timeout_minutes}
            )
            failed_runs.append(r_id)
            
    await db.flush()
    return failed_runs
