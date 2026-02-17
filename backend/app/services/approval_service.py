"""Approval service — HITL management."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Approval


async def create_approval(
    db: AsyncSession,
    run_id: str,
    node_id: str,
    prompt: str,
    decision_type: str,
    options: list[str] | None = None,
    context_data: dict[str, Any] | None = None,
) -> Approval:
    approval = Approval(
        run_id=run_id,
        node_id=node_id,
        prompt=prompt,
        decision_type=decision_type,
        options_json=json.dumps(options) if options else None,
        context_data_json=json.dumps(context_data) if context_data else None,
    )
    db.add(approval)
    await db.flush()
    await db.refresh(approval)
    return approval


async def list_approvals(db: AsyncSession, status: str | None = None) -> list[Approval]:
    stmt = select(Approval).order_by(Approval.created_at.desc())
    if status:
        stmt = stmt.where(Approval.status == status)
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def get_approval(db: AsyncSession, approval_id: str) -> Approval | None:
    return await db.get(Approval, approval_id)


async def submit_decision(
    db: AsyncSession,
    approval_id: str,
    decision: str,
    decided_by: str | None = None,
    payload: dict[str, Any] | None = None,
) -> Approval | None:
    approval = await db.get(Approval, approval_id)
    if not approval or approval.status != "pending":
        return None
    approval.status = decision  # "approved" or "rejected"
    approval.decided_by = decided_by
    approval.decision_json = json.dumps(payload) if payload else None
    approval.decided_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(approval)
    return approval
