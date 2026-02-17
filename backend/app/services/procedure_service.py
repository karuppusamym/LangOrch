"""Procedures business logic."""

from __future__ import annotations

import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Procedure


async def import_procedure(db: AsyncSession, ckp: dict[str, Any], project_id: str | None = None) -> Procedure:
    """Validate minimal required fields and persist a CKP procedure."""
    procedure_id = ckp.get("procedure_id")
    version = ckp.get("version")
    if not procedure_id or not version:
        raise ValueError("CKP must contain procedure_id and version at the root.")

    proc = Procedure(
        procedure_id=procedure_id,
        version=version,
        name=ckp.get("name", procedure_id),
        status=ckp.get("status", "draft"),
        effective_date=ckp.get("effective_date"),
        description=ckp.get("description"),
        ckp_json=json.dumps(ckp),
        project_id=project_id,
    )
    db.add(proc)
    await db.flush()
    await db.refresh(proc)
    return proc


async def list_procedures(db: AsyncSession, project_id: str | None = None) -> list[Procedure]:
    stmt = select(Procedure).order_by(Procedure.created_at.desc())
    if project_id:
        stmt = stmt.where(Procedure.project_id == project_id)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_procedure(db: AsyncSession, procedure_id: str, version: str | None = None) -> Procedure | None:
    stmt = select(Procedure).where(Procedure.procedure_id == procedure_id)
    if version:
        stmt = stmt.where(Procedure.version == version)
    else:
        stmt = stmt.order_by(Procedure.created_at.desc())
    result = await db.execute(stmt)
    return result.scalars().first()


async def list_versions(db: AsyncSession, procedure_id: str) -> list[Procedure]:
    stmt = (
        select(Procedure)
        .where(Procedure.procedure_id == procedure_id)
        .order_by(Procedure.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def update_procedure(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    ckp: dict[str, Any],
) -> Procedure | None:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return None

    if ckp.get("procedure_id") and ckp.get("procedure_id") != procedure_id:
        raise ValueError("procedure_id in CKP does not match target procedure_id")
    if ckp.get("version") and ckp.get("version") != version:
        raise ValueError("version in CKP does not match target version")

    proc.name = ckp.get("name", proc.name)
    proc.status = ckp.get("status", proc.status)
    proc.effective_date = ckp.get("effective_date", proc.effective_date)
    proc.description = ckp.get("description", proc.description)
    proc.ckp_json = json.dumps(ckp)
    await db.flush()
    await db.refresh(proc)
    return proc


async def delete_procedure_version(db: AsyncSession, procedure_id: str, version: str) -> bool:
    proc = await get_procedure(db, procedure_id, version)
    if not proc:
        return False
    await db.delete(proc)
    await db.flush()
    return True
