"""Procedures API router."""

from __future__ import annotations

import json

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.schemas.procedures import ProcedureCreate, ProcedureDetail, ProcedureOut, ProcedureUpdate
from app.services import procedure_service
from app.services.graph_service import extract_graph

router = APIRouter()


@router.post("", response_model=ProcedureOut, status_code=201)
async def import_procedure(body: ProcedureCreate, db: AsyncSession = Depends(get_db)):
    try:
        proc = await procedure_service.import_procedure(db, body.ckp_json, body.project_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return proc


@router.get("", response_model=list[ProcedureOut])
async def list_procedures(
    project_id: str | None = None,
    status: str | None = None,
    tags: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    return await procedure_service.list_procedures(db, project_id, status=status, tags=tag_list)


@router.get("/{procedure_id}/versions", response_model=list[ProcedureOut])
async def list_versions(procedure_id: str, db: AsyncSession = Depends(get_db)):
    return await procedure_service.list_versions(db, procedure_id)


@router.get("/{procedure_id}/{version}/graph")
async def get_procedure_graph(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    """Return the workflow graph topology (nodes + edges) for visualisation."""
    proc = await procedure_service.get_procedure(db, procedure_id, version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    ckp = json.loads(proc.ckp_json)
    workflow_graph = ckp.get("workflow_graph", {})
    return extract_graph(workflow_graph)


@router.get("/{procedure_id}/{version}", response_model=ProcedureDetail)
async def get_procedure(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    proc = await procedure_service.get_procedure(db, procedure_id, version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return proc


@router.put("/{procedure_id}/{version}", response_model=ProcedureOut)
async def update_procedure(
    procedure_id: str,
    version: str,
    body: ProcedureUpdate,
    db: AsyncSession = Depends(get_db),
):
    try:
        proc = await procedure_service.update_procedure(db, procedure_id, version, body.ckp_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return proc


@router.delete("/{procedure_id}/{version}")
async def delete_procedure_version(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    deleted = await procedure_service.delete_procedure_version(db, procedure_id, version)
    if not deleted:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return {"deleted": True, "procedure_id": procedure_id, "version": version}
