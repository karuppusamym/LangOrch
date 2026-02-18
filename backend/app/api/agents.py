"""Agent instances API router."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import AgentInstance
from app.schemas.agents import AgentInstanceCreate, AgentInstanceOut, AgentInstanceUpdate

router = APIRouter()


@router.get("", response_model=list[AgentInstanceOut])
async def list_agents(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).order_by(AgentInstance.name))
    return list(result.scalars().all())


@router.post("", response_model=AgentInstanceOut, status_code=201)
async def register_agent(body: AgentInstanceCreate, db: AsyncSession = Depends(get_db)):
    agent_id = body.agent_id or f"{body.channel}_{body.name.replace(' ', '_').lower()}"
    resource_key = body.resource_key or f"{body.channel}_default"

    inst = AgentInstance(
        agent_id=agent_id,
        name=body.name,
        channel=body.channel,
        base_url=body.base_url,
        concurrency_limit=body.concurrency_limit,
        resource_key=resource_key,
        capabilities=",".join(body.capabilities) if body.capabilities else None,
    )
    db.add(inst)
    await db.flush()
    await db.refresh(inst)
    return inst


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
