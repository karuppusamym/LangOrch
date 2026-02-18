"""Resource lease management API endpoints."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.services.lease_service import list_active_leases, release_lease

router = APIRouter()


class LeaseOut(BaseModel):
    lease_id: str
    resource_key: str
    run_id: str
    node_id: str | None
    step_id: str | None
    acquired_at: str
    expires_at: str
    released_at: str | None
    is_active: bool

    model_config = {"from_attributes": True}


@router.get("", response_model=list[LeaseOut])
async def list_leases(
    resource_key: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    """List all currently active (unreleased + unexpired) resource leases."""
    leases = await list_active_leases(db, resource_key=resource_key)
    return [
        LeaseOut(
            lease_id=str(lease.lease_id),
            resource_key=lease.resource_key,
            run_id=lease.run_id,
            node_id=lease.node_id,
            step_id=lease.step_id,
            acquired_at=lease.acquired_at.isoformat() if lease.acquired_at else "",
            expires_at=lease.expires_at.isoformat(),
            released_at=lease.released_at.isoformat() if lease.released_at else None,
            is_active=lease.released_at is None,
        )
        for lease in leases
    ]


@router.delete("/{lease_id}", status_code=204)
async def revoke_lease(
    lease_id: str,
    db: AsyncSession = Depends(get_db),
):
    """Force-release a lease by ID (admin action for stuck runs)."""
    await release_lease(db, lease_id)
    await db.commit()
