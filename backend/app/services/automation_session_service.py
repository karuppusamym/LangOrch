"""Durable automation session storage for stateful agents."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AutomationSession


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def create_session(
    db: AsyncSession,
    *,
    agent_id: str,
    channel: str,
    timeout_s: int,
    data: dict[str, Any],
    run_id: str | None = None,
    tenant_id: str | None = None,
    user_id: str | None = None,
) -> AutomationSession:
    now = _utcnow()
    expires_at = now + timedelta(seconds=max(1, int(timeout_s)))
    row = AutomationSession(
        agent_id=agent_id,
        channel=channel,
        run_id=run_id,
        tenant_id=tenant_id,
        user_id=user_id,
        data_json=json.dumps(data or {}),
        created_at=now,
        last_used_at=now,
        expires_at=expires_at,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_session(db: AsyncSession, session_id: str, *, timeout_s: int | None = None) -> AutomationSession | None:
    row = await db.get(AutomationSession, session_id)
    if row is None:
        return None
    now = _utcnow()
    row.closed_at = _ensure_utc(row.closed_at)
    row.created_at = _ensure_utc(row.created_at) or now
    row.last_used_at = _ensure_utc(row.last_used_at) or now
    row.expires_at = _ensure_utc(row.expires_at) or now
    if row.closed_at is not None or row.expires_at <= now:
        await db.delete(row)
        await db.flush()
        return None
    row.last_used_at = now
    if timeout_s is not None:
        row.expires_at = now + timedelta(seconds=max(1, int(timeout_s)))
    await db.flush()
    await db.refresh(row)
    return row


async def update_session(db: AsyncSession, session_id: str, *, timeout_s: int | None = None, data: dict[str, Any]) -> AutomationSession | None:
    row = await get_session(db, session_id, timeout_s=timeout_s)
    if row is None:
        return None
    merged = json.loads(row.data_json or "{}")
    merged.update(data or {})
    row.data_json = json.dumps(merged)
    await db.flush()
    await db.refresh(row)
    return row


async def close_session(db: AsyncSession, session_id: str) -> AutomationSession | None:
    row = await db.get(AutomationSession, session_id)
    if row is None:
        return None
    row.closed_at = _utcnow()
    await db.flush()
    await db.refresh(row)
    return row


async def cleanup_expired_sessions(db: AsyncSession, *, agent_id: str | None = None, channel: str | None = None) -> int:
    stmt = delete(AutomationSession).where(
        (AutomationSession.closed_at.is_not(None)) | (AutomationSession.expires_at <= _utcnow())
    )
    if agent_id:
        stmt = stmt.where(AutomationSession.agent_id == agent_id)
    if channel:
        stmt = stmt.where(AutomationSession.channel == channel)
    result = await db.execute(stmt)
    await db.flush()
    return int(result.rowcount or 0)


async def count_active_sessions(db: AsyncSession, *, agent_id: str | None = None, channel: str | None = None) -> int:
    stmt = select(func.count()).select_from(AutomationSession).where(
        AutomationSession.closed_at.is_(None),
        AutomationSession.expires_at > _utcnow(),
    )
    if agent_id:
        stmt = stmt.where(AutomationSession.agent_id == agent_id)
    if channel:
        stmt = stmt.where(AutomationSession.channel == channel)
    result = await db.execute(stmt)
    return int(result.scalar_one() or 0)


def session_snapshot(row: AutomationSession) -> dict[str, Any]:
    created_at = _ensure_utc(row.created_at) or _utcnow()
    last_used_at = _ensure_utc(row.last_used_at) or created_at
    expires_at = _ensure_utc(row.expires_at) or last_used_at
    return {
        "session_id": row.session_id,
        "created_at": created_at.timestamp(),
        "last_used_at": last_used_at.timestamp(),
        "expires_at": expires_at.timestamp(),
        "data": json.loads(row.data_json or "{}"),
    }
