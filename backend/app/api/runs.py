"""Runs API router."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db, async_session
from app.db.models import RunJob
from app.schemas.runs import ArtifactOut, RunCreate, RunDiagnostics, RunOut, CheckpointMetadata, CheckpointState
from app.services import procedure_service, run_service
from app.services import checkpoint_service
from app.utils.metrics import get_metrics_summary
from app.utils.run_cancel import mark_cancelled as _mark_run_cancelled, mark_cancelled_db as _mark_run_cancelled_db
from app.utils.input_vars import validate_input_vars
from app.worker.enqueue import enqueue_run, requeue_run
from app.auth import require_role
from app.auth.deps import Principal

router = APIRouter()


@router.post("", response_model=RunOut, status_code=201)
async def create_run(body: RunCreate, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    # Resolve procedure
    proc = await procedure_service.get_procedure(db, body.procedure_id, body.procedure_version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")

    # Validate input_vars against the procedure's variables_schema (if any)
    import json as _json
    _ckp = _json.loads(proc.ckp_json) if proc.ckp_json else {}
    _schema = _ckp.get("variables_schema") or {}
    if _schema:
        _errors = validate_input_vars(_schema, body.input_vars)
        if _errors:
            raise HTTPException(
                status_code=422,
                detail={"message": "Invalid input_vars", "errors": _errors},
            )

    run = await run_service.create_run(
        db,
        procedure_id=proc.procedure_id,
        procedure_version=proc.version,
        input_vars=body.input_vars,
        # inherit project from procedure if caller didn't specify
        project_id=body.project_id or proc.project_id,
    )

    # Atomically enqueue a durable RunJob in the same transaction as the Run.
    enqueue_run(db, run.run_id)
    # get_db commits on success — both Run + RunJob land atomically.
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(
    procedure_id: str | None = None,
    project_id: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
    db: AsyncSession = Depends(get_db),
):
    return await run_service.list_runs(
        db,
        procedure_id=procedure_id,
        project_id=project_id,
        status=status,
        created_from=created_from,
        created_to=created_to,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/metrics/summary")
async def get_metrics():
    """Get operational metrics summary."""
    return get_metrics_summary()


@router.get("/queue")
async def get_queue_stats(db: AsyncSession = Depends(get_db)):
    """Return job queue depth by status plus the next pending jobs (max 20)."""
    counts_result = await db.execute(
        select(RunJob.status, func.count().label("count")).group_by(RunJob.status)
    )
    depth_by_status: dict[str, int] = {row.status: row.count for row in counts_result}

    pending_result = await db.execute(
        select(RunJob)
        .where(RunJob.status.in_(["queued", "retrying"]))
        .order_by(RunJob.priority.desc(), RunJob.available_at.asc())
        .limit(20)
    )
    next_jobs = [
        {
            "job_id": j.job_id,
            "run_id": j.run_id,
            "status": j.status,
            "priority": j.priority,
            "attempts": j.attempts,
            "max_attempts": j.max_attempts,
            "available_at": j.available_at.isoformat() if j.available_at else None,
            "locked_by": j.locked_by,
        }
        for j in pending_result.scalars()
    ]
    return {
        "depth_by_status": depth_by_status,
        "total_pending": depth_by_status.get("queued", 0) + depth_by_status.get("retrying", 0),
        "total_running": depth_by_status.get("running", 0),
        "total_done": depth_by_status.get("done", 0),
        "total_failed": depth_by_status.get("failed", 0),
        "next_jobs": next_jobs,
    }


@router.get("/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.get("/{run_id}/artifacts", response_model=list[ArtifactOut])
async def get_run_artifacts(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return await run_service.list_artifacts(db, run_id)


@router.get("/{run_id}/diagnostics", response_model=RunDiagnostics)
async def get_run_diagnostics(run_id: str, db: AsyncSession = Depends(get_db)):
    diagnostics = await run_service.get_run_diagnostics(db, run_id)
    if not diagnostics:
        raise HTTPException(status_code=404, detail="Run not found")
    return diagnostics


@router.get("/{run_id}/checkpoints", response_model=list[CheckpointMetadata])
async def list_run_checkpoints(run_id: str, db: AsyncSession = Depends(get_db)):
    """List all checkpoints for a run."""
    run = await run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    thread_id = run.thread_id or run_id
    checkpoints = await checkpoint_service.list_checkpoints(thread_id)
    return checkpoints


@router.get("/{run_id}/checkpoints/{checkpoint_id}", response_model=CheckpointState)
async def get_checkpoint_state(run_id: str, checkpoint_id: str, db: AsyncSession = Depends(get_db)):
    """Get state at a specific checkpoint."""
    run = await run_service.get_run(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    
    thread_id = run.thread_id or run_id
    state = await checkpoint_service.get_checkpoint_state(thread_id, checkpoint_id)
    if not state:
        raise HTTPException(status_code=404, detail="Checkpoint not found")
    return state


@router.post("/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    # Set DB-level flag (works across processes / between worker heartbeats)
    await _mark_run_cancelled_db(run_id, db)
    # Also signal in-process event for immediate effect in embedded mode
    _mark_run_cancelled(run_id)
    run = await run_service.update_run_status(db, run_id, "canceled")
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/retry", response_model=RunOut)
async def retry_run(run_id: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    existing = await run_service.get_run(db, run_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Run not found")

    run = await run_service.prepare_retry(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    # prepare_retry reuses the same run_id, so an existing RunJob already
    # exists for this run.  Use requeue_run to UPDATE it back to queued
    # instead of attempting a second INSERT (which would fail the unique
    # constraint on run_jobs.run_id).
    await requeue_run(db, run.run_id)
    return run


@router.delete("/cleanup/history")
async def cleanup_runs(
    before: datetime,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_role("admin")),
):
    deleted_count = await run_service.cleanup_runs_before(db, before=before, status=status)
    await db.commit()
    return {"deleted_count": deleted_count, "before": before.isoformat(), "status": status}


@router.delete("/{run_id}")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    deleted = await run_service.delete_run(db, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    await db.commit()
    return {"deleted": True, "run_id": run_id}
