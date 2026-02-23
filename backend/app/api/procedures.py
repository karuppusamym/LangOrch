"""Procedures API router."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.schemas.procedures import ProcedureCreate, ProcedureDetail, ProcedureOut, ProcedureUpdate
from app.services import procedure_service
from app.services.graph_service import extract_graph
from app.services.explain_service import explain_procedure
from app.compiler.parser import parse_ckp
from app.compiler.validator import validate_ir
from app.compiler.binder import bind_executors
from app.auth import require_role
from app.auth.deps import Principal

router = APIRouter()


class ExplainRequest(BaseModel):
    """Optional body for the explain endpoint — can supply input variable values."""
    input_vars: dict[str, Any] = {}


@router.post("", response_model=ProcedureOut, status_code=201)
async def import_procedure(body: ProcedureCreate, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
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
    search: str | None = None,
    metadata_search: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    tag_list = [t.strip() for t in tags.split(",") if t.strip()] if tags else None
    return await procedure_service.list_procedures(
        db, project_id, status=status, tags=tag_list, search=search, metadata_search=metadata_search
    )


@router.get("/{procedure_id}/versions", response_model=list[ProcedureOut])
async def list_versions(procedure_id: str, db: AsyncSession = Depends(get_db)):
    return await procedure_service.list_versions(db, procedure_id)


@router.get("/{procedure_id}/{version}/graph")
async def get_procedure_graph(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    """Return the workflow graph topology (nodes + edges) for visualisation."""
    # Accept "latest" as a sentinel meaning "most recent version"
    resolved_version = None if version.lower() == "latest" else version
    proc = await procedure_service.get_procedure(db, procedure_id, resolved_version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    ckp = json.loads(proc.ckp_json)
    workflow_graph = ckp.get("workflow_graph", {})
    return extract_graph(workflow_graph)


@router.post("/{procedure_id}/{version}/explain")
async def explain_procedure_route(
    procedure_id: str,
    version: str,
    body: ExplainRequest | None = None,
    db: AsyncSession = Depends(get_db),
):
    """Dry-run static analysis — return node/edge/variable/route descriptions.

    No execution or DB writes occur.  Useful for pre-flight validation and
    documenting what a procedure will do before running it.
    """
    proc = await procedure_service.get_procedure(db, procedure_id, version)
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    try:
        ckp = json.loads(proc.ckp_json)
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        if errors:
            raise ValueError("; ".join(errors))
        ir = bind_executors(ir)
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"IR compilation failed: {exc}")
    input_vars = (body.input_vars if body else None) or {}
    return explain_procedure(ir, input_vars=input_vars)


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
    _principal: Principal = Depends(require_role("operator")),
):
    try:
        proc = await procedure_service.update_procedure(db, procedure_id, version, body.ckp_json)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return proc


@router.delete("/{procedure_id}/{version}")
async def delete_procedure_version(procedure_id: str, version: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    deleted = await procedure_service.delete_procedure_version(db, procedure_id, version)
    if not deleted:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return {"deleted": True, "procedure_id": procedure_id, "version": version}


class StatusPatch(BaseModel):
    """Body for the PATCH /{id}/{version}/status endpoint."""
    status: str  # draft | active | deprecated | archived


@router.patch("/{procedure_id}/{version}/status", response_model=ProcedureOut)
async def patch_procedure_status(
    procedure_id: str,
    version: str,
    body: StatusPatch,
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_role("operator")),
):
    """Transition a procedure version's status (draft → active → deprecated → archived)
    without re-uploading the full CKP JSON."""
    try:
        proc = await procedure_service.patch_procedure_status(db, procedure_id, version, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if not proc:
        raise HTTPException(status_code=404, detail="Procedure not found")
    return proc
