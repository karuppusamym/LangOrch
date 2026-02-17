"""Agent registry — manages registered agent instances and their capabilities."""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentInstance

logger = logging.getLogger("langorch.registry.agent")


async def register_agent(
    db: AsyncSession,
    agent_id: str,
    name: str,
    channel: str,
    base_url: str,
    capabilities: list[str] | None = None,
    resource_key: str | None = None,
    concurrency_limit: int = 1,
    metadata: dict[str, Any] | None = None,
) -> AgentInstance:
    """Register or update an agent instance."""
    existing = await db.get(AgentInstance, agent_id)
    if existing:
        existing.name = name
        existing.channel = channel
        existing.base_url = base_url
        existing.capabilities = ",".join(capabilities or [])
        existing.resource_key = resource_key or f"{channel}_default"
        existing.concurrency_limit = concurrency_limit
        existing.status = "online"
        await db.flush()
        return existing

    agent = AgentInstance(
        agent_id=agent_id,
        name=name,
        channel=channel,
        base_url=base_url,
        capabilities=",".join(capabilities or []),
        resource_key=resource_key or f"{channel}_default",
        concurrency_limit=concurrency_limit,
        status="online",
    )
    db.add(agent)
    await db.flush()
    return agent


async def get_agent(db: AsyncSession, agent_id: str) -> AgentInstance | None:
    return await db.get(AgentInstance, agent_id)


async def list_agents(db: AsyncSession, channel: str | None = None) -> list[AgentInstance]:
    stmt = select(AgentInstance)
    if channel:
        stmt = stmt.where(AgentInstance.channel == channel)
    result = await db.execute(stmt.order_by(AgentInstance.name))
    return list(result.scalars().all())


async def find_agent_for_action(
    db: AsyncSession, channel: str, action: str
) -> AgentInstance | None:
    """Find an online agent that can handle the given channel/action."""
    agents = await list_agents(db, channel)
    for agent in agents:
        if agent.status != "online":
            continue
        caps = agent.capabilities.split(",") if agent.capabilities else []
        if not caps or action in caps or "*" in caps:
            return agent
    return None


async def set_agent_status(db: AsyncSession, agent_id: str, status: str) -> None:
    agent = await db.get(AgentInstance, agent_id)
    if agent:
        agent.status = status
        await db.flush()
