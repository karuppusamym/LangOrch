"""Case-type to procedure allow-list policy service."""

from __future__ import annotations

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Case, CaseProcedurePolicy, Procedure


async def list_policies(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    case_type: str | None = None,
    enabled_only: bool = False,
) -> list[CaseProcedurePolicy]:
    stmt = select(CaseProcedurePolicy).order_by(
        CaseProcedurePolicy.case_type.asc(),
        CaseProcedurePolicy.procedure_id.asc(),
    )
    if project_id is not None:
        stmt = stmt.where(CaseProcedurePolicy.project_id == project_id)
    if case_type is not None:
        stmt = stmt.where(CaseProcedurePolicy.case_type == case_type)
    if enabled_only:
        stmt = stmt.where(CaseProcedurePolicy.enabled.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_policy(
    db: AsyncSession,
    *,
    project_id: str | None,
    case_type: str,
    procedure_id: str,
    enabled: bool = True,
) -> CaseProcedurePolicy:
    existing = await db.execute(
        select(CaseProcedurePolicy).where(
            and_(
                CaseProcedurePolicy.project_id == project_id,
                CaseProcedurePolicy.case_type == case_type,
                CaseProcedurePolicy.procedure_id == procedure_id,
            )
        )
    )
    row = existing.scalar_one_or_none()
    if row is not None:
        row.enabled = enabled
        await db.flush()
        await db.refresh(row)
        return row
    row = CaseProcedurePolicy(
        project_id=project_id,
        case_type=case_type,
        procedure_id=procedure_id,
        enabled=enabled,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_policy(db: AsyncSession, policy_id: str) -> bool:
    row = await db.get(CaseProcedurePolicy, policy_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def resolve_allowed_procedure_ids(
    db: AsyncSession,
    *,
    project_id: str | None,
    case_type: str | None,
) -> tuple[bool, list[str]]:
    if not case_type:
        return False, []

    project_stmt = select(CaseProcedurePolicy).where(
        and_(
            CaseProcedurePolicy.project_id == project_id,
            CaseProcedurePolicy.case_type == case_type,
            CaseProcedurePolicy.enabled.is_(True),
        )
    )
    project_rows = list((await db.execute(project_stmt)).scalars().all())
    if project_rows:
        return True, sorted({row.procedure_id for row in project_rows})

    global_stmt = select(CaseProcedurePolicy).where(
        and_(
            CaseProcedurePolicy.project_id.is_(None),
            CaseProcedurePolicy.case_type == case_type,
            CaseProcedurePolicy.enabled.is_(True),
        )
    )
    global_rows = list((await db.execute(global_stmt)).scalars().all())
    if global_rows:
        return True, sorted({row.procedure_id for row in global_rows})

    return False, []


async def assert_case_allows_procedure(db: AsyncSession, case: Case, procedure_id: str) -> None:
    restricted, procedure_ids = await resolve_allowed_procedure_ids(
        db,
        project_id=case.project_id,
        case_type=case.case_type,
    )
    if restricted and procedure_id not in procedure_ids:
        raise ValueError(
            f"Procedure '{procedure_id}' is not allowed for case_type '{case.case_type}'"
        )


async def list_launchable_procedures_for_case(
    db: AsyncSession,
    case: Case,
) -> list[Procedure]:
    stmt = select(Procedure).order_by(Procedure.created_at.desc())
    if case.project_id:
        stmt = stmt.where(Procedure.project_id == case.project_id)
    stmt = stmt.where(Procedure.status.notin_(["archived", "deprecated"]))
    restricted, procedure_ids = await resolve_allowed_procedure_ids(
        db,
        project_id=case.project_id,
        case_type=case.case_type,
    )
    if restricted:
        if not procedure_ids:
            return []
        stmt = stmt.where(Procedure.procedure_id.in_(procedure_ids))
    result = await db.execute(stmt)
    return list(result.scalars().all())

