"""Runtime executor dispatcher — resolves executors DYNAMICALLY from the
agent registry (DB) at execution time, NOT from hardcoded mappings.

Flow:
  1. Check if step has a compile-time binding (internal actions only).
  2. If unbound, look at the CKP node's `agent` field (e.g. "DESKTOP", "WEB").
     - That `agent` value is the **channel** used to search the agent_instances table.
  3. Query agent_instances WHERE channel = node.agent AND status = 'online'.
     - If the agent has capabilities listed, check that the step's action is in them.
     - If capabilities = '*' or empty, the agent accepts all actions for its channel.
  4. If a matching agent is found → dispatch via AgentClient (HTTP to agent's base_url).
  5. If no agent is found → attempt MCP tool fallback (if configured).
  6. If neither → raise an error: "No executor registered for channel X, action Y".

This is the ONLY place where action→executor resolution happens.
The compiler/binder only tags internal actions — everything else lands here.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from datetime import datetime, timezone

from app.compiler.ir import ExecutorBinding, IRNode, IRStep
from app.connectors.agent_client import AgentClient
from app.connectors.mcp_client import MCPClient
from app.config import settings
from app.db.models import AgentInstance

# Must match main._CIRCUIT_RESET_SECONDS — agents stay circuit-open for this long
_CIRCUIT_RESET_SECONDS: int = 300

logger = logging.getLogger("langorch.runtime.dispatch")

# ── Round-robin counters — keyed by "{channel}:{pool_id}" ─────────────────────
# Monotonically increasing; mod-selected against live agent list each dispatch.
# Module-level so they survive across requests within a process.
_pool_counters: dict[str, int] = defaultdict(int)


class NoExecutorError(Exception):
    """Raised when no registered agent or tool can handle the action."""

    def __init__(self, channel: str, action: str):
        self.channel = channel
        self.action = action
        super().__init__(
            f"No executor registered for channel='{channel}', action='{action}'. "
            f"Register an agent for this channel via the portal."
        )


async def resolve_executor(
    db: AsyncSession,
    node: IRNode,
    step: IRStep,
) -> ExecutorBinding:
    """Dynamically resolve which executor should handle this step.

    Resolution order:
      1. Already bound at compile time (internal) → return as-is.
      2. Query agent_instances by channel (= node.agent) → agent_http binding.
      3. MCP tool fallback (future) → mcp_tool binding.
      4. Nothing found → raise NoExecutorError.
    """
    # 1. Already bound (internal actions like log, wait, set_variable)
    if step.executor_binding and step.executor_binding.kind == "internal":
        return step.executor_binding

    # 2. Determine channel from the CKP node's agent field
    channel = (node.agent or "").upper()
    if not channel:
        # No agent declared on this node — treat as internal/generic
        return ExecutorBinding(kind="internal", ref=step.action)

    # Normalize channel to lowercase for DB lookup
    channel_lower = channel.lower()

    # 3. Query the agent registry for a matching online agent
    agent = await _find_capable_agent(db, channel_lower, step.action)
    if agent:
        return ExecutorBinding(
            kind="agent_http",
            ref=agent.base_url,  # actual URL, not a hardcoded name
            mode="step",
        )

    # 4. MCP fallback (if configured)
    if settings.MCP_BASE_URL:
        return ExecutorBinding(kind="mcp_tool", ref=settings.MCP_BASE_URL, mode="step")

    # 5. Nothing found
    raise NoExecutorError(channel_lower, step.action)


async def _find_capable_agent(
    db: AsyncSession, channel: str, action: str
) -> AgentInstance | None:
    """Find an online agent whose channel matches and capabilities include the action.

    Selection strategy
    ------------------
    * Agents are first grouped by ``pool_id``.
    * Within a pool the *next* agent is chosen via a monotonic round-robin
      counter (``_pool_counters["{channel}:{pool_id}"]``).
    * Agents without a ``pool_id`` form their own implicit pool keyed by
      ``{channel}:standalone``.
    * Circuit-open agents are skipped; the counter does NOT advance for them
      so the next healthy agent in the pool is tried.
    """
    stmt = (
        select(AgentInstance)
        .where(AgentInstance.channel == channel)
        .where(AgentInstance.status == "online")
        .order_by(AgentInstance.pool_id.nulls_last(), AgentInstance.agent_id)
    )
    result = await db.execute(stmt)
    agents = list(result.scalars().all())

    now = datetime.now(timezone.utc)

    def _is_healthy(agent: AgentInstance) -> bool:
        """Return True if the agent's circuit breaker is not open."""
        if agent.circuit_open_at is None:
            return True
        circuit_ts = agent.circuit_open_at
        if circuit_ts.tzinfo is None:
            circuit_ts = circuit_ts.replace(tzinfo=timezone.utc)
        elapsed = (now - circuit_ts).total_seconds()
        if elapsed < _CIRCUIT_RESET_SECONDS:
            logger.debug(
                "Skipping circuit-open agent %s (open for %.0fs / %ds reset)",
                agent.agent_id, elapsed, _CIRCUIT_RESET_SECONDS,
            )
            return False
        return True

    def _has_capability(agent: AgentInstance) -> bool:
        caps = [c.strip() for c in agent.capabilities.split(",") if c.strip()] if agent.capabilities else []
        return not caps or "*" in caps or action in caps

    # Group capable, healthy agents by pool key
    pools: dict[str, list[AgentInstance]] = defaultdict(list)
    for agent in agents:
        if _is_healthy(agent) and _has_capability(agent):
            pool_key = f"{channel}:{agent.pool_id or 'standalone'}"
            pools[pool_key].append(agent)

    if not pools:
        return None

    # Use the first (sorted) pool that has agents.
    # When agents share a pool_id they will all end up in the same list.
    pool_key = sorted(pools.keys())[0]
    pool_agents = pools[pool_key]

    # Round-robin within the pool
    idx = _pool_counters[pool_key] % len(pool_agents)
    _pool_counters[pool_key] += 1
    return pool_agents[idx]


async def dispatch_to_agent(
    agent_url: str,
    action: str,
    params: dict[str, Any],
    run_id: str,
    node_id: str,
    step_id: str,
) -> dict[str, Any]:
    """Actually call the agent over HTTP and return the result."""
    client = AgentClient(agent_url)
    try:
        result = await client.execute_action(
            action=action,
            params=params,
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
        )
        return result
    finally:
        await client.close()


async def dispatch_to_mcp(
    mcp_url: str,
    tool_name: str,
    arguments: dict[str, Any],
    run_id: str = "",
    node_id: str = "",
    step_id: str = "",
) -> dict[str, Any]:
    """Call an MCP tool server and return the result."""
    client = MCPClient(mcp_url)
    try:
        return await client.call_tool(tool_name, arguments, run_id=run_id, node_id=node_id, step_id=step_id)
    finally:
        await client.close()
