"""Batch jobs API."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import Principal
from app.auth.roles import require_role
from app.db.engine import get_db
from app.schemas.batch_jobs import BatchJobCreate, BatchJobItemOut, BatchJobOperationResult, BatchJobOut
from app.services import batch_job_service, project_service

router = APIRouter()


@router.get("", response_model=list[BatchJobOut])
async def list_batch_jobs(
    project_id: str | None = None,
    procedure_id: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    return await batch_job_service.list_batch_jobs(
        db,
        project_id=project_id,
        procedure_id=procedure_id,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=BatchJobOut, status_code=201)
async def create_batch_job(
    body: BatchJobCreate,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("operator")),
):
    if body.project_id:
        proj = await project_service.get_project(db, body.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
    try:
        job = await batch_job_service.create_batch_job(
            db,
            name=body.name,
            procedure_id=body.procedure_id,
            procedure_version=body.procedure_version or "latest",
            payload_text=body.payload_text,
            source_format=body.source_format,
            project_id=body.project_id,
            create_case_per_item=body.create_case_per_item,
            case_type=body.case_type,
            title_field=body.title_field,
            external_ref_field=body.external_ref_field,
            tags=body.tags,
            trigger_type="manual",
            triggered_by=principal.identity,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return job


@router.get("/{batch_job_id}", response_model=BatchJobOut)
async def get_batch_job(
    batch_job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return job


@router.get("/{batch_job_id}/items", response_model=list[BatchJobItemOut])
async def list_batch_job_items(
    batch_job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    return await batch_job_service.list_batch_job_items(db, batch_job_id)


@router.post("/{batch_job_id}/cancel", response_model=BatchJobOperationResult)
async def cancel_batch_job(
    batch_job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    items = await batch_job_service.cancel_batch_job(db, batch_job_id)
    return BatchJobOperationResult(
        batch_job_id=batch_job_id,
        affected=len(items),
        item_ids=[item.item_id for item in items],
    )


@router.post("/{batch_job_id}/retry-failed", response_model=BatchJobOperationResult)
async def retry_failed_batch_job_items(
    batch_job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    items = await batch_job_service.retry_failed_batch_job_items(db, batch_job_id)
    return BatchJobOperationResult(
        batch_job_id=batch_job_id,
        affected=len(items),
        item_ids=[item.item_id for item in items],
    )


@router.post("/{batch_job_id}/items/{item_id}/retry", response_model=BatchJobItemOut)
async def retry_batch_job_item(
    batch_job_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    try:
        item = await batch_job_service.retry_batch_job_item(db, batch_job_id, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    return item


@router.post("/{batch_job_id}/items/{item_id}/cancel", response_model=BatchJobItemOut)
async def cancel_batch_job_item(
    batch_job_id: str,
    item_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    try:
        item = await batch_job_service.cancel_batch_job_item(db, batch_job_id, item_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not item:
        raise HTTPException(status_code=404, detail="Batch item not found")
    return item


@router.get("/{batch_job_id}/failed-export")
async def export_failed_batch_job_items(
    batch_job_id: str,
    db: AsyncSession = Depends(get_db),
    _: Principal = Depends(require_role("operator")),
):
    job = await batch_job_service.get_batch_job(db, batch_job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Batch job not found")
    csv_body = await batch_job_service.export_failed_batch_job_items_csv(db, batch_job_id)
    safe_name = quote(f"{job.name or batch_job_id}-failed-rows.csv")
    return Response(
        content=csv_body,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{safe_name}"},
    )
