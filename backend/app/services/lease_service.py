"""Resource lease service — enforces concurrency limits for agent instances."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.models import AgentInstance, ResourceLease


async def try_acquire_lease(
    db: AsyncSession,
    resource_key: str,
    run_id: str,
    node_id: str | None = None,
    step_id: str | None = None,
) -> ResourceLease | None:
    """Try to acquire a lease on resource_key. Returns None if resource is at capacity."""
    now = datetime.now(timezone.utc)

    # Find how many active (unexpired, unreleased) leases exist on this resource
    active_stmt = select(ResourceLease).where(
        and_(
            ResourceLease.resource_key == resource_key,
            ResourceLease.released_at.is_(None),
            ResourceLease.expires_at > now,
        )
    )
    active_result = await db.execute(active_stmt)
    active_leases = list(active_result.scalars().all())

    # Find concurrency limit for this resource
    inst_stmt = select(AgentInstance).where(AgentInstance.resource_key == resource_key)
    inst_result = await db.execute(inst_stmt)
    instance = inst_result.scalars().first()
    limit = instance.concurrency_limit if instance else 1

    if len(active_leases) >= limit:
        return None  # busy

    lease = ResourceLease(
        resource_key=resource_key,
        run_id=run_id,
        node_id=node_id,
        step_id=step_id,
        expires_at=now + timedelta(seconds=settings.LEASE_TTL_SECONDS),
    )
    db.add(lease)
    await db.flush()
    await db.refresh(lease)
    return lease


async def release_lease(db: AsyncSession, lease_id: str) -> None:
    lease = await db.get(ResourceLease, lease_id)
    if lease and lease.released_at is None:
        lease.released_at = datetime.now(timezone.utc)
        await db.flush()


async def list_active_leases(db: AsyncSession, resource_key: str | None = None) -> list[ResourceLease]:
    now = datetime.now(timezone.utc)
    stmt = select(ResourceLease).where(
        and_(
            ResourceLease.released_at.is_(None),
            ResourceLease.expires_at > now,
        )
    )
    if resource_key:
        stmt = stmt.where(ResourceLease.resource_key == resource_key)
    result = await db.execute(stmt)
    return list(result.scalars().all())
