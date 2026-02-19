"""Agent instances API router."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import AgentInstance
from app.schemas.agents import AgentInstanceCreate, AgentInstanceOut, AgentInstanceUpdate

logger = logging.getLogger("langorch.api.agents")
router = APIRouter()


async def _probe_capabilities(base_url: str) -> list[str] | None:
    """Try to fetch capabilities from a live agent. Returns None if unreachable."""
    url = base_url.rstrip("/") + "/capabilities"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
            caps = data.get("capabilities")
            if isinstance(caps, list):
                return [str(c) for c in caps if c]
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not probe capabilities from %s: %s", url, exc)
    return None


@router.get("", response_model=list[AgentInstanceOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).order_by(AgentInstance.name))
    return list(result.scalars().all())


@router.get("/probe-capabilities", response_model=list[str])
async def probe_capabilities(base_url: str = Query(..., description="Agent base URL to probe")):
    """Fetch capabilities from a live agent without registering it."""
    caps = await _probe_capabilities(base_url)
    if caps is None:
        raise HTTPException(status_code=502, detail=f"Could not reach agent at {base_url}/capabilities")
    return caps


@router.post("", response_model=AgentInstanceOut, status_code=201)
async def register_agent(body: AgentInstanceCreate, db: AsyncSession = Depends(get_db)):
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
        capabilities=",".join(resolved_caps) if resolved_caps else None,
    )
    db.add(inst)
    await db.flush()
    await db.refresh(inst)
    return inst


@router.get("/{agent_id}", response_model=AgentInstanceOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentInstanceOut)
async def update_agent(agent_id: str, body: AgentInstanceUpdate, db: AsyncSession = Depends(get_db)):
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
        agent.capabilities = ",".join(body.capabilities) if body.capabilities else None
    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    return agent


@router.delete("/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    await db.delete(agent)
    await db.flush()
    return None


@router.post("/{agent_id}/sync-capabilities", response_model=AgentInstanceOut)
async def sync_capabilities(agent_id: str, db: AsyncSession = Depends(get_db)):
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

    agent.capabilities = ",".join(caps) if caps else None
    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    logger.info("Synced capabilities for agent '%s': %s", agent_id, caps)
    return agent
