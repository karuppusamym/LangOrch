"""Audit log CRUD — read-only API for the Audit page."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_roles
from app.db.engine import get_db
from app.db.models import AuditEvent

router = APIRouter(prefix="/api/audit", tags=["audit"])


# ── Helpers ────────────────────────────────────────────────────────────────────


async def emit_audit(
    db: AsyncSession,
    *,
    category: str,
    action: str,
    actor: str = "system",
    description: str = "",
    resource_type: str | None = None,
    resource_id: str | None = None,
    meta: dict[str, Any] | None = None,
) -> None:
    """Insert an audit event row.  Call this from other routers after mutations."""
    ev = AuditEvent(
        category=category,
        action=action,
        actor=actor,
        description=description,
        resource_type=resource_type,
        resource_id=resource_id,
        meta_json=json.dumps(meta) if meta else None,
    )
    db.add(ev)
    # Caller is responsible for committing; we do NOT commit here so we stay
    # within the same transaction as the mutation being logged.


# ── Routes ─────────────────────────────────────────────────────────────────────


@router.get("")
async def list_audit_events(
    category: str | None = Query(None, description="Filter by category (user_mgmt|secret_mgmt|auth|config|run)"),
    actor: str | None = Query(None, description="Filter by actor username"),
    action: str | None = Query(None, description="Filter by action type"),
    search: str | None = Query(None, description="Full-text search in description"),
    since: datetime | None = Query(None, description="ISO timestamp lower bound"),
    until: datetime | None = Query(None, description="ISO timestamp upper bound"),
    limit: int = Query(200, ge=1, le=1000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_roles(["admin", "manager", "operator", "approver", "viewer"])),
) -> dict:
    stmt = select(AuditEvent).order_by(desc(AuditEvent.ts))

    if category:
        stmt = stmt.where(AuditEvent.category == category)
    if actor:
        stmt = stmt.where(AuditEvent.actor == actor)
    if action:
        stmt = stmt.where(AuditEvent.action == action)
    if search:
        stmt = stmt.where(AuditEvent.description.ilike(f"%{search}%"))
    if since:
        stmt = stmt.where(AuditEvent.ts >= since)
    if until:
        stmt = stmt.where(AuditEvent.ts <= until)

    total_stmt = stmt.with_only_columns(AuditEvent.event_id)  # type: ignore[arg-type]
    results = await db.execute(stmt.limit(limit).offset(offset))
    rows = results.scalars().all()

    return {
        "events": [
            {
                "event_id": r.event_id,
                "ts": r.ts.isoformat(),
                "category": r.category,
                "action": r.action,
                "actor": r.actor,
                "description": r.description,
                "resource_type": r.resource_type,
                "resource_id": r.resource_id,
                "meta": json.loads(r.meta_json) if r.meta_json else None,
            }
            for r in rows
        ],
        "limit": limit,
        "offset": offset,
    }
