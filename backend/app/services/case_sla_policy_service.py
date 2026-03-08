"""SLA policy profiles for case management."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import CaseSlaPolicy


async def list_policies(
    db: AsyncSession,
    project_id: str | None = None,
    case_type: str | None = None,
    priority: str | None = None,
    enabled_only: bool = False,
) -> list[CaseSlaPolicy]:
    stmt = select(CaseSlaPolicy).order_by(CaseSlaPolicy.created_at.desc())
    if project_id:
        stmt = stmt.where(CaseSlaPolicy.project_id == project_id)
    if case_type:
        stmt = stmt.where(CaseSlaPolicy.case_type == case_type)
    if priority:
        stmt = stmt.where(CaseSlaPolicy.priority == priority)
    if enabled_only:
        stmt = stmt.where(CaseSlaPolicy.enabled.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_policy(db: AsyncSession, policy_id: str) -> CaseSlaPolicy | None:
    return await db.get(CaseSlaPolicy, policy_id)


async def create_policy(
    db: AsyncSession,
    name: str,
    due_minutes: int,
    project_id: str | None = None,
    case_type: str | None = None,
    priority: str | None = None,
    breach_status: str = "escalated",
    enabled: bool = True,
) -> CaseSlaPolicy:
    policy = CaseSlaPolicy(
        name=name,
        project_id=project_id,
        case_type=case_type,
        priority=priority,
        due_minutes=due_minutes,
        breach_status=breach_status,
        enabled=enabled,
    )
    db.add(policy)
    await db.flush()
    await db.refresh(policy)
    return policy


async def update_policy(
    db: AsyncSession,
    policy_id: str,
    patch: dict,
) -> CaseSlaPolicy | None:
    policy = await db.get(CaseSlaPolicy, policy_id)
    if not policy:
        return None
    for key, value in patch.items():
        if hasattr(policy, key):
            setattr(policy, key, value)
    await db.flush()
    await db.refresh(policy)
    return policy


async def delete_policy(db: AsyncSession, policy_id: str) -> bool:
    policy = await db.get(CaseSlaPolicy, policy_id)
    if not policy:
        return False
    await db.delete(policy)
    await db.flush()
    return True


def _specificity_score(
    policy: CaseSlaPolicy,
    project_id: str | None,
    case_type: str | None,
    priority: str | None,
) -> tuple[int, int, int]:
    project_match = 1 if policy.project_id == project_id else 0
    case_type_match = 1 if policy.case_type == case_type else 0
    priority_match = 1 if policy.priority == priority else 0
    return (
        project_match + case_type_match + priority_match,
        project_match,
        case_type_match + priority_match,
    )


async def resolve_policy(
    db: AsyncSession,
    project_id: str | None,
    case_type: str | None,
    priority: str | None,
) -> CaseSlaPolicy | None:
    stmt = (
        select(CaseSlaPolicy)
        .where(CaseSlaPolicy.enabled.is_(True))
        .where(or_(CaseSlaPolicy.project_id == project_id, CaseSlaPolicy.project_id.is_(None)))
        .where(or_(CaseSlaPolicy.case_type == case_type, CaseSlaPolicy.case_type.is_(None)))
        .where(or_(CaseSlaPolicy.priority == priority, CaseSlaPolicy.priority.is_(None)))
    )
    candidates = list((await db.execute(stmt)).scalars().all())
    if not candidates:
        return None

    # Prefer highest specificity, then project-specific, then newest.
    candidates.sort(
        key=lambda p: (
            _specificity_score(p, project_id, case_type, priority),
            p.updated_at,
        ),
        reverse=True,
    )
    return candidates[0]


async def compute_sla_due_at(
    db: AsyncSession,
    *,
    created_at: datetime | None = None,
    project_id: str | None = None,
    case_type: str | None = None,
    priority: str | None = None,
) -> datetime | None:
    policy = await resolve_policy(db, project_id=project_id, case_type=case_type, priority=priority)
    if not policy:
        return None
    base = created_at or datetime.now(timezone.utc)
    if base.tzinfo is None:
        base = base.replace(tzinfo=timezone.utc)
    return base + timedelta(minutes=policy.due_minutes)
