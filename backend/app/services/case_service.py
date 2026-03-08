"""Case CRUD and timeline service."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import case as sql_case, delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Case, CaseEvent, Run

logger = logging.getLogger("langorch.case_service")


async def list_cases(
    db: AsyncSession,
    project_id: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    external_ref: str | None = None,
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> list[Case]:
    stmt = select(Case)
    if project_id:
        stmt = stmt.where(Case.project_id == project_id)
    if status:
        stmt = stmt.where(Case.status == status)
    if owner:
        stmt = stmt.where(Case.owner == owner)
    if external_ref:
        stmt = stmt.where(Case.external_ref == external_ref)

    stmt = stmt.order_by(Case.created_at.asc() if order == "asc" else Case.created_at.desc())
    stmt = stmt.limit(limit).offset(offset)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_case(db: AsyncSession, case_id: str) -> Case | None:
    return await db.get(Case, case_id)


async def create_case(
    db: AsyncSession,
    title: str,
    project_id: str | None = None,
    external_ref: str | None = None,
    case_type: str | None = None,
    description: str | None = None,
    status: str = "open",
    priority: str = "normal",
    owner: str | None = None,
    sla_due_at: datetime | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
) -> Case:
    if sla_due_at is None:
        from app.services import case_sla_policy_service

        sla_due_at = await case_sla_policy_service.compute_sla_due_at(
            db,
            project_id=project_id,
            case_type=case_type,
            priority=priority,
        )

    case = Case(
        title=title,
        project_id=project_id,
        external_ref=external_ref,
        case_type=case_type,
        description=description,
        status=status,
        priority=priority,
        owner=owner,
        sla_due_at=sla_due_at,
        tags_json=json.dumps(tags) if tags is not None else None,
        metadata_json=json.dumps(metadata) if metadata is not None else None,
    )
    db.add(case)
    await db.flush()
    await db.refresh(case)
    await emit_case_event(db, case.case_id, "case_created")
    return case


async def update_case(
    db: AsyncSession,
    case_id: str,
    patch: dict[str, Any],
    actor: str | None = None,
) -> Case | None:
    case = await db.get(Case, case_id)
    if not case:
        return None

    for key, value in patch.items():
        if key == "tags":
            case.tags_json = json.dumps(value) if value is not None else None
        elif key == "metadata":
            case.metadata_json = json.dumps(value) if value is not None else None
        elif key == "sla_due_at":
            case.sla_due_at = value
            # Reset breach marker if SLA is moved into the future.
            if value is not None and value > datetime.now(timezone.utc):
                case.sla_breached_at = None
        elif hasattr(case, key):
            setattr(case, key, value)

    await db.flush()
    await db.refresh(case)
    await emit_case_event(db, case_id, "case_updated", actor=actor, payload={"fields": sorted(patch.keys())})
    return case


async def delete_case(db: AsyncSession, case_id: str) -> bool:
    case = await db.get(Case, case_id)
    if not case:
        return False

    linked_runs = await db.execute(
        select(func.count()).select_from(Run).where(Run.case_id == case_id)
    )
    if int(linked_runs.scalar() or 0) > 0:
        raise ValueError("Cannot delete case with linked runs")

    await db.execute(delete(CaseEvent).where(CaseEvent.case_id == case_id))
    await db.delete(case)
    await db.flush()
    return True


async def list_case_events(db: AsyncSession, case_id: str, limit: int = 200) -> list[CaseEvent]:
    stmt = (
        select(CaseEvent)
        .where(CaseEvent.case_id == case_id)
        .order_by(CaseEvent.ts.asc())
        .limit(limit)
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def emit_case_event(
    db: AsyncSession,
    case_id: str,
    event_type: str,
    actor: str | None = None,
    payload: dict[str, Any] | None = None,
) -> CaseEvent:
    event = CaseEvent(
        case_id=case_id,
        event_type=event_type,
        actor=actor,
        payload_json=json.dumps(payload) if payload is not None else None,
    )
    db.add(event)
    await db.flush()
    await db.refresh(event)
    # Queue outbound webhook deliveries in the same transaction as the event row.
    try:
        from app.services import case_webhook_service

        case = await db.get(Case, case_id)
        await case_webhook_service.enqueue_case_event_webhooks(
            db,
            {
                "event_id": event.event_id,
                "event_type": event_type,
                "case_id": case_id,
                "project_id": case.project_id if case else None,
                "actor": actor,
                "ts": event.ts.isoformat() if event.ts else None,
                "payload": payload or {},
            },
        )
    except Exception as exc:
        # Keep case event writes resilient; failures here are surfaced to logs.
        logger.warning("Failed to enqueue case webhook delivery for event=%s: %s", event.event_id, exc)
    return event


def _priority_rank_expr():
    return sql_case(
        (Case.priority == "urgent", 0),
        (Case.priority == "high", 1),
        (Case.priority == "normal", 2),
        (Case.priority == "low", 3),
        else_=9,
    )


async def list_queue_cases(
    db: AsyncSession,
    project_id: str | None = None,
    owner: str | None = None,
    only_unassigned: bool = False,
    include_terminal: bool = False,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    now = datetime.now(timezone.utc)
    terminal_statuses = ("resolved", "closed", "completed", "cancelled", "canceled")
    breach_expr = sql_case(
        ((Case.sla_due_at.is_not(None) & (Case.sla_due_at <= now)), 0),
        else_=1,
    )

    stmt = select(Case).order_by(breach_expr.asc(), _priority_rank_expr().asc(), Case.created_at.asc())
    if project_id:
        stmt = stmt.where(Case.project_id == project_id)
    if owner:
        stmt = stmt.where(Case.owner == owner)
    if only_unassigned:
        stmt = stmt.where(Case.owner.is_(None))
    if not include_terminal:
        stmt = stmt.where(Case.status.notin_(terminal_statuses))
    stmt = stmt.limit(limit).offset(offset)

    rows = (await db.execute(stmt)).scalars().all()
    items: list[dict[str, Any]] = []
    for row in rows:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        due = row.sla_due_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)

        is_breached = due is not None and due <= now
        sla_remaining: float | None = None
        if due is not None:
            sla_remaining = (due - now).total_seconds()
        priority_rank = {"urgent": 0, "high": 1, "normal": 2, "low": 3}.get(row.priority, 9)
        items.append(
            {
                "case_id": row.case_id,
                "project_id": row.project_id,
                "external_ref": row.external_ref,
                "case_type": row.case_type,
                "title": row.title,
                "description": row.description,
                "status": row.status,
                "priority": row.priority,
                "owner": row.owner,
                "sla_due_at": row.sla_due_at,
                "sla_breached_at": row.sla_breached_at,
                "tags": json.loads(row.tags_json) if row.tags_json else None,
                "metadata": json.loads(row.metadata_json) if row.metadata_json else None,
                "created_at": row.created_at,
                "updated_at": row.updated_at,
                "priority_rank": priority_rank,
                "age_seconds": (now - created_at).total_seconds(),
                "sla_remaining_seconds": sla_remaining,
                "is_sla_breached": is_breached,
            }
        )
    return items


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return float(values[0])
    ordered = sorted(values)
    rank = (pct / 100.0) * (len(ordered) - 1)
    lo = int(rank)
    hi = min(lo + 1, len(ordered) - 1)
    frac = rank - lo
    return float(ordered[lo] + (ordered[hi] - ordered[lo]) * frac)


async def get_queue_analytics(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    risk_window_minutes: int = 60,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    risk_cutoff = now + timedelta(minutes=max(1, risk_window_minutes))
    terminal_statuses = ("resolved", "closed", "completed", "cancelled", "canceled")

    stmt = select(Case).where(Case.status.notin_(terminal_statuses))
    if project_id:
        stmt = stmt.where(Case.project_id == project_id)
    rows = list((await db.execute(stmt)).scalars().all())

    total_active = len(rows)
    unassigned = 0
    breached = 0
    breach_risk = 0
    wait_ages: list[float] = []
    wait_by_priority_raw: dict[str, list[float]] = {}
    wait_by_case_type_raw: dict[str, list[float]] = {}
    for row in rows:
        created_at = row.created_at
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        wait_age = max(0.0, (now - created_at).total_seconds())
        wait_ages.append(wait_age)
        priority_key = row.priority or "unknown"
        case_type_key = row.case_type or "unknown"
        wait_by_priority_raw.setdefault(priority_key, []).append(wait_age)
        wait_by_case_type_raw.setdefault(case_type_key, []).append(wait_age)

        if row.owner is None:
            unassigned += 1

        due = row.sla_due_at
        if due is not None and due.tzinfo is None:
            due = due.replace(tzinfo=timezone.utc)
        if due is not None and due <= now:
            breached += 1
        elif due is not None and now < due <= risk_cutoff:
            breach_risk += 1

    claims_stmt = select(CaseEvent.payload_json).where(CaseEvent.event_type == "case_claimed")
    claims_cutoff = now - timedelta(hours=24)
    claims_stmt = claims_stmt.where(CaseEvent.ts >= claims_cutoff)
    if project_id:
        claims_stmt = claims_stmt.join(Case, Case.case_id == CaseEvent.case_id).where(Case.project_id == project_id)
    claim_payload_rows = (await db.execute(claims_stmt)).scalars().all()

    total_claims = 0
    reassignments = 0
    for payload_json in claim_payload_rows:
        total_claims += 1
        try:
            payload = json.loads(payload_json) if payload_json else {}
        except Exception:
            payload = {}
        previous_owner = payload.get("previous_owner")
        new_owner = payload.get("owner")
        if previous_owner and new_owner and previous_owner != new_owner:
            reassignments += 1

    reassignment_rate = (reassignments / total_claims * 100.0) if total_claims > 0 else 0.0

    releases_stmt = select(func.count()).select_from(CaseEvent).where(
        CaseEvent.event_type == "case_released",
        CaseEvent.ts >= claims_cutoff,
    )
    if project_id:
        releases_stmt = releases_stmt.join(Case, Case.case_id == CaseEvent.case_id).where(Case.project_id == project_id)
    total_releases = int((await db.execute(releases_stmt)).scalar() or 0)

    abandonment_denominator = total_claims + total_releases
    abandonment_rate = (total_releases / abandonment_denominator * 100.0) if abandonment_denominator > 0 else 0.0

    wait_by_priority = {
        key: {
            "count": len(values),
            "wait_p50_seconds": _percentile(values, 50.0),
            "wait_p95_seconds": _percentile(values, 95.0),
        }
        for key, values in wait_by_priority_raw.items()
    }
    wait_by_case_type = {
        key: {
            "count": len(values),
            "wait_p50_seconds": _percentile(values, 50.0),
            "wait_p95_seconds": _percentile(values, 95.0),
        }
        for key, values in wait_by_case_type_raw.items()
    }
    breach_risk_pct = (breach_risk / total_active * 100.0) if total_active > 0 else 0.0

    return {
        "total_active_cases": total_active,
        "unassigned_cases": unassigned,
        "breached_cases": breached,
        "breach_risk_next_window_cases": breach_risk,
        "breach_risk_next_window_percent": breach_risk_pct,
        "wait_p50_seconds": _percentile(wait_ages, 50.0),
        "wait_p95_seconds": _percentile(wait_ages, 95.0),
        "wait_by_priority": wait_by_priority,
        "wait_by_case_type": wait_by_case_type,
        "reassignment_rate_24h": reassignment_rate,
        "abandonment_rate_24h": abandonment_rate,
    }


async def claim_case(
    db: AsyncSession,
    case_id: str,
    owner: str,
    set_in_progress: bool = True,
    actor: str | None = None,
) -> Case | None:
    case = await db.get(Case, case_id)
    if not case:
        return None
    if case.owner and case.owner != owner:
        raise ValueError(f"Case already claimed by {case.owner}")

    previous_owner = case.owner
    case.owner = owner
    if set_in_progress and case.status == "open":
        case.status = "in_progress"
    await db.flush()
    await db.refresh(case)
    await emit_case_event(
        db,
        case_id,
        "case_claimed",
        actor=actor or owner,
        payload={"owner": owner, "previous_owner": previous_owner},
    )
    return case


async def release_case(
    db: AsyncSession,
    case_id: str,
    owner: str | None = None,
    set_open: bool = False,
    actor: str | None = None,
) -> Case | None:
    case = await db.get(Case, case_id)
    if not case:
        return None
    if owner and case.owner and case.owner != owner:
        raise ValueError(f"Case claimed by {case.owner}; cannot release as {owner}")

    previous_owner = case.owner
    case.owner = None
    if set_open and case.status == "in_progress":
        case.status = "open"
    await db.flush()
    await db.refresh(case)
    await emit_case_event(
        db,
        case_id,
        "case_released",
        actor=actor or owner,
        payload={"previous_owner": previous_owner},
    )
    return case


async def mark_sla_breaches(
    db: AsyncSession,
    now: datetime | None = None,
) -> list[str]:
    now = now or datetime.now(timezone.utc)
    terminal_statuses = ("resolved", "closed", "completed", "cancelled", "canceled")
    stmt = (
        select(Case)
        .where(Case.sla_due_at.is_not(None))
        .where(Case.sla_due_at <= now)
        .where(Case.sla_breached_at.is_(None))
        .where(Case.status.notin_(terminal_statuses))
    )
    cases = list((await db.execute(stmt)).scalars().all())
    breached_ids: list[str] = []
    for case in cases:
        case.sla_breached_at = now
        breach_status = "escalated"
        try:
            from app.services import case_sla_policy_service

            policy = await case_sla_policy_service.resolve_policy(
                db,
                project_id=case.project_id,
                case_type=case.case_type,
                priority=case.priority,
            )
            if policy and policy.breach_status:
                breach_status = policy.breach_status
        except Exception:
            pass
        if case.status in ("open", "in_progress"):
            case.status = breach_status
        breached_ids.append(case.case_id)
        await emit_case_event(
            db,
            case.case_id,
            "case_sla_breached",
            payload={
                "sla_due_at": case.sla_due_at.isoformat() if case.sla_due_at else None,
                "breached_at": now.isoformat(),
            },
        )
        # Record SLA breach metric for SLO monitoring
        try:
            from app.utils.metrics import record_sla_breach
            record_sla_breach(case_type=case.case_type, priority=case.priority)
        except Exception:
            pass
    if cases:
        await db.flush()
    return breached_ids
