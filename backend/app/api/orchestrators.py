"""Orchestrator worker status API router."""

from __future__ import annotations

import logging
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends
from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import OrchestratorWorker
from app.schemas.orchestrator import OrchestratorWorkerOut
from app.auth import require_role
from app.auth.deps import Principal

logger = logging.getLogger("langorch.api.orchestrators")
router = APIRouter()

@router.get("", response_model=list[OrchestratorWorkerOut])
async def list_orchestrators(
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_role("viewer"))
):
    """Return all known orchestrator workers."""
    # First, let's opportunisticly prune dead workers that haven't heartbeated in 5 minutes
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=5)
    
    await db.execute(delete(OrchestratorWorker).where(OrchestratorWorker.last_heartbeat_at < cutoff))
    await db.commit()

    result = await db.execute(select(OrchestratorWorker).order_by(OrchestratorWorker.last_heartbeat_at.desc()))
    return list(result.scalars().all())
