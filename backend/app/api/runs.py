"""Runs API router."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db, async_session
from app.schemas.runs import ArtifactOut, RunCreate, RunDiagnostics, RunOut, CheckpointMetadata, CheckpointState
from app.services import procedure_service, run_service
from app.services import checkpoint_service
from app.services.execution_service import execute_run
from app.utils.metrics import get_metrics_summary

router = APIRouter()


@router.post("", response_model=RunOut, status_code=201)
async def create_run(body: RunCreate, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    # Resolve procedure
    proc = await procedure_service.get_procedure(db, body.procedure_id, body.procedure_version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")

    run = await run_service.create_run(
        db,
        procedure_id=proc.procedure_id,
        procedure_version=proc.version,
        input_vars=body.input_vars,
        project_id=body.project_id,
    )

    # Ensure run is committed before background worker tries to load it.
    await db.commit()
    background.add_task(execute_run, run.run_id, async_session)
    return run


@router.get("", response_model=list[RunOut])
async def list_runs(
    project_id: str | None = None,
    status: str | None = None,
    created_from: datetime | None = None,
    created_to: datetime | None = None,
    order: str = "desc",
    db: AsyncSession = Depends(get_db),
):
    return await run_service.list_runs(
        db,
        project_id=project_id,
        status=status,
        created_from=created_from,
        created_to=created_to,
        order=order,
    )


@router.get("/metrics/summary")
async def get_metrics():
    """Get operational metrics summary."""
    return get_metrics_summary()


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
async def cancel_run(run_id: str, db: AsyncSession = Depends(get_db)):
    run = await run_service.update_run_status(db, run_id, "canceled")
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


@router.post("/{run_id}/retry", response_model=RunOut)
async def retry_run(run_id: str, background: BackgroundTasks, db: AsyncSession = Depends(get_db)):
    existing = await run_service.get_run(db, run_id)
    if not existing:
        raise HTTPException(status_code=404, detail="Run not found")

    run = await run_service.prepare_retry(db, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    await db.commit()
    background.add_task(execute_run, run.run_id, async_session)
    return run


@router.delete("/cleanup/history")
async def cleanup_runs(
    before: datetime,
    status: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    deleted_count = await run_service.cleanup_runs_before(db, before=before, status=status)
    await db.commit()
    return {"deleted_count": deleted_count, "before": before.isoformat(), "status": status}


@router.delete("/{run_id}")
async def delete_run(run_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await run_service.delete_run(db, run_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Run not found")
    await db.commit()
    return {"deleted": True, "run_id": run_id}
