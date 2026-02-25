"""Agent instances API router."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import AgentInstance, ResourceLease
from app.schemas.agents import AgentInstanceCreate, AgentInstanceOut, AgentInstanceUpdate, AgentHeartbeat, AgentBootstrapOut
from app.auth import require_role
from app.auth.deps import Principal

logger = logging.getLogger("langorch.api.agents")
router = APIRouter()


async def _probe_capabilities(base_url: str) -> list[dict] | None:
    """Try to fetch capabilities from a live agent. Returns None if unreachable."""
    url = base_url.rstrip("/") + "/capabilities"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            caps = data.get("capabilities")
            if isinstance(caps, list):
                normalized = []
                for c in caps:
                    if isinstance(c, dict):
                        normalized.append(c)
                    elif c:
                        normalized.append({"name": str(c), "type": "tool", "is_batch": False})
                return normalized
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not probe capabilities from %s: %s", url, exc)
    return None


@router.get("", response_model=list[AgentInstanceOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).order_by(AgentInstance.name))
    return list(result.scalars().all())


@router.get("/probe-capabilities", response_model=list[dict])
async def probe_capabilities(base_url: str = Query(..., description="Agent base URL to probe")):
    """Fetch capabilities from a live agent without registering it."""
    caps = await _probe_capabilities(base_url)
    if caps is None:
        raise HTTPException(status_code=502, detail=f"Could not reach agent at {base_url}/capabilities")
    return caps


@router.post("", response_model=AgentInstanceOut, status_code=201)
async def register_agent(body: AgentInstanceCreate, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    agent_id = body.agent_id or f"{body.channel}_{body.name.replace(' ', '_').lower()}"
    resource_key = body.resource_key or f"{body.channel}_default"

    # Auto-discover capabilities from the live agent if none provided
    resolved_caps = body.capabilities
    if not resolved_caps:
        resolved_caps = await _probe_capabilities(body.base_url)

    inst = AgentInstance(
        agent_id=agent_id,
        name=body.name,
        channel=body.channel,
        base_url=body.base_url,
        concurrency_limit=body.concurrency_limit,
        resource_key=resource_key,
        pool_id=body.pool_id,
        capabilities=json.dumps([c.model_dump() if hasattr(c, 'model_dump') else c for c in resolved_caps]) if resolved_caps else None,
    )
    db.add(inst)
    await db.flush()
    await db.refresh(inst)
    return inst


@router.get("/pools")
async def get_pool_stats(db: AsyncSession = Depends(get_db)):
    """Return per-pool aggregated agent statistics.

    Each pool (pool_id + channel) reports:
    - Total agent count and per-status breakdown
    - Aggregate concurrency_limit (total capacity)
    - Active leases (not-yet-released, not yet expired)
    - Available capacity = concurrency_limit_total - active_leases
    """
    # Use naive UTC so comparisons with DB-stored naive datetimes work correctly
    from datetime import datetime as _dt
    now = _dt.utcnow()

    # Fetch all agents
    agents_result = await db.execute(select(AgentInstance).order_by(AgentInstance.pool_id, AgentInstance.channel))
    agents = list(agents_result.scalars().all())

    # Count active (non-released, non-expired) leases per resource_key
    leases_result = await db.execute(
        select(ResourceLease.resource_key, func.count().label("active"))
        .where(ResourceLease.released_at.is_(None), ResourceLease.expires_at > now)
        .group_by(ResourceLease.resource_key)
    )
    active_by_key: dict[str, int] = {row.resource_key: row.active for row in leases_result}

    # Aggregate by (pool_id, channel)
    pools: dict[tuple[str, str], dict] = {}
    for agent in agents:
        key = (agent.pool_id or "__default__", agent.channel)
        if key not in pools:
            pools[key] = {
                "pool_id": agent.pool_id,
                "channel": agent.channel,
                "agent_count": 0,
                "status_breakdown": {},
                "concurrency_limit_total": 0,
                "active_leases": 0,
                "available_capacity": 0,
                "circuit_open_count": 0,
            }
        p = pools[key]
        p["agent_count"] += 1
        p["status_breakdown"][agent.status] = p["status_breakdown"].get(agent.status, 0) + 1
        p["concurrency_limit_total"] += agent.concurrency_limit
        p["active_leases"] += active_by_key.get(agent.resource_key, 0)
        if agent.circuit_open_at and agent.circuit_open_at > now:
            p["circuit_open_count"] += 1

    # Compute available capacity
    for p in pools.values():
        p["available_capacity"] = max(0, p["concurrency_limit_total"] - p["active_leases"])

    return list(pools.values())


@router.get("/{agent_id}", response_model=AgentInstanceOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentInstanceOut)
async def update_agent(agent_id: str, body: AgentInstanceUpdate, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    if body.status is not None:
        agent.status = body.status
    if body.base_url is not None:
        agent.base_url = body.base_url
    if body.concurrency_limit is not None:
        agent.concurrency_limit = body.concurrency_limit
    if body.capabilities is not None:
        agent.capabilities = json.dumps([c.model_dump() if hasattr(c, 'model_dump') else c for c in body.capabilities]) if body.capabilities else None
    if body.pool_id is not None:
        agent.pool_id = body.pool_id
    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.flush()
    return None


@router.post("/{agent_id}/sync-capabilities", response_model=AgentInstanceOut)
async def sync_capabilities(agent_id: str, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    """Pull capabilities from the live agent and save them to the DB."""
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    caps = await _probe_capabilities(agent.base_url)
    if caps is None:
        raise HTTPException(
            status_code=502,
            detail=f"Could not reach agent at {agent.base_url}/capabilities",
        )

    agent.capabilities = json.dumps(caps) if caps else None
    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    logger.info("Synced capabilities for agent '%s': %s", agent_id, caps)
    return agent


@router.get("/bootstrap/{channel}", response_model=AgentBootstrapOut)
async def bootstrap_agent(channel: str, db: AsyncSession = Depends(get_db)):
    """Return bootstrap configuration for an agent starting up in a given channel."""
    # This could eventually be driven by a DB table for channel configs.
    # For now, return safe default values.
    return AgentBootstrapOut(
        channel=channel,
        default_pool=f"{channel}_default",
        recommended_concurrency=5,
    )


@router.post("/heartbeat")
async def agent_heartbeat(body: AgentHeartbeat, db: AsyncSession = Depends(get_db)):
    """Receive heartbeat from an active agent instance."""
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == body.agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.status = body.status
    now = datetime.now(timezone.utc)
    agent.last_heartbeat_at = now
    
    # If the agent reports online, reset the circuit breaker and consecutive failures.
    if body.status == "online":
        agent.circuit_open_at = None
        agent.consecutive_failures = 0

    agent.updated_at = now
    await db.flush()
    return {"status": "ok", "agent_id": agent.agent_id}
