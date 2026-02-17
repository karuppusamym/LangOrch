"""Agent instances API router."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import get_db
from app.db.models import AgentInstance
from app.schemas.agents import AgentInstanceCreate, AgentInstanceOut

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
