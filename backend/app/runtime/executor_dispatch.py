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

# ── Agent Affinity Tracking — keyed by "{run_id}:{channel}" ──────────────────
# Maps a run to a specific agent instance to maintain session affinity
# (e.g. keeping the same browser session for all WEB steps in a run).
_run_agent_affinity: dict[str, str] = {}


def clear_run_affinity(run_id: str) -> None:
    """Clear all affinity bindings for a given run to prevent memory leaks."""
    keys_to_remove = [k for k in _run_agent_affinity.keys() if k.startswith(f"{run_id}:")]
    for k in keys_to_remove:
        del _run_agent_affinity[k]
        logger.debug("Cleared agent affinity binding: %s", k)


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
    run_id: str | None = None,
) -> tuple["ExecutorBinding", str]:
    """Dynamically resolve which executor should handle this step.

    Returns:
        (ExecutorBinding, capability_type) where capability_type is
        'tool' (fast, block and wait) or 'workflow' (slow, use webhook).

    Resolution order:
      1. Already bound at compile time (internal) → return as-is.
      2. Query agent_instances by channel (= node.agent) → agent_http binding.
      3. MCP tool fallback (future) → mcp_tool binding.
      4. Nothing found → raise NoExecutorError.
    """
    # 1. Already bound (internal actions like log, wait, set_variable)
    if step.executor_binding and step.executor_binding.kind == "internal":
        return step.executor_binding, "tool"

    # 2. Determine channel from the CKP node's agent field
    channel = (node.agent or "").upper()
    if not channel:
        # No agent declared on this node — treat as internal/generic
        return ExecutorBinding(kind="internal", ref=step.action), "tool"

    # Normalize channel to lowercase for DB lookup
    channel_lower = channel.lower()

    # 3. Query the agent registry for a matching online agent
    agent, cap_type = await _find_capable_agent(db, channel_lower, step.action, run_id)
    if agent:
        return ExecutorBinding(
            kind="agent_http",
            ref=agent.base_url,  # actual URL, not a hardcoded name
            mode="step",
        ), cap_type

    # 4. MCP fallback (if configured)
    if settings.MCP_BASE_URL:
        return ExecutorBinding(kind="mcp_tool", ref=settings.MCP_BASE_URL, mode="step"), "tool"

    # 5. Nothing found
    raise NoExecutorError(channel_lower, step.action)


async def _find_capable_agent(
    db: AsyncSession, channel: str, action: str, run_id: str | None = None
) -> tuple["AgentInstance | None", str]:
    """Find an online agent whose channel matches and capabilities include the action.

    Returns:
        (agent, capability_type) where capability_type is 'tool' or 'workflow'.
        If no agent found, returns (None, 'tool').

    Selection strategy
    ------------------
    * First checks `_run_agent_affinity` for an existing binding for this run+channel.
    * If affinity agent is offline/circuit-open, affinity is broken.
    * Otherwise, agents are grouped by ``pool_id``.
    * Within a pool the *next* agent is chosen via a monotonic round-robin
      counter (``_pool_counters["{channel}:{pool_id}"]``).
    * Agents without a ``pool_id`` form their own implicit pool keyed by
      ``{channel}:standalone``.
    * Circuit-open agents are skipped; the counter does NOT advance for them
      so the next healthy agent in the pool is tried.
    """
    import json as _json

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

    def _parse_caps(agent: AgentInstance) -> list[dict]:
        """Parse the JSON-stored capabilities list. Handles both JSON and legacy CSV."""
        raw = agent.capabilities
        if not raw:
            return []
        raw = raw.strip()
        if raw.startswith("["):
            try:
                parsed = _json.loads(raw)
                if isinstance(parsed, list):
                    result_list = []
                    for item in parsed:
                        if isinstance(item, dict):
                            result_list.append(item)
                        elif isinstance(item, str):
                            result_list.append({"name": item, "type": "tool"})
                    return result_list
            except _json.JSONDecodeError:
                pass
        # Legacy CSV fallback
        return [{"name": c.strip(), "type": "tool"} for c in raw.split(",") if c.strip()]

    def _has_capability(agent: AgentInstance) -> tuple[bool, str]:
        """Return (can_handle, capability_type)."""
        caps = _parse_caps(agent)
        if not caps:
            return True, "tool"  # Empty = accept all, assume tool
        for cap in caps:
            name = cap.get("name", "")
            if name == "*" or name == action:
                return True, cap.get("type", "tool")
        return False, "tool"

    # Pre-filter healthy and capable agents
    capable_agents_with_types = [
        (a, t) for a in agents
        if _is_healthy(a)
        for ok, t in [_has_capability(a)]
        if ok
    ]
    if not capable_agents_with_types:
        return None, "tool"

    # Check for affinity first
    affinity_key = f"{run_id}:{channel}" if run_id else None
    if affinity_key and affinity_key in _run_agent_affinity:
        affinity_agent_id = _run_agent_affinity[affinity_key]
        for a, t in capable_agents_with_types:
            if a.agent_id == affinity_agent_id:
                logger.debug("Affinity hit: routing %s action to agent %s for run %s", channel, a.agent_id, run_id)
                return a, t
        # If we got here, the affinity agent is apparently offline or circuit-open.
        logger.warning("Affinity broken: agent %s for run %s channel %s is no longer healthy/capable.", affinity_agent_id, run_id, channel)
        del _run_agent_affinity[affinity_key]

    # Group capable, healthy agents by pool key
    pools: dict[str, list[tuple[AgentInstance, str]]] = defaultdict(list)
    for agent, cap_type in capable_agents_with_types:
        pool_key = f"{channel}:{agent.pool_id or 'standalone'}"
        pools[pool_key].append((agent, cap_type))

    if not pools:
        return None, "tool"

    # Use the first (sorted) pool that has agents.
    pool_key = sorted(pools.keys())[0]
    pool_entries = pools[pool_key]

    # Round-robin within the pool
    idx = _pool_counters[pool_key] % len(pool_entries)
    _pool_counters[pool_key] += 1
    selected_agent, selected_cap_type = pool_entries[idx]

    # Establish new affinity if we have a run_id
    if affinity_key:
        _run_agent_affinity[affinity_key] = selected_agent.agent_id
        logger.debug("Established new affinity: routing %s action to agent %s for run %s", channel, selected_agent.agent_id, run_id)

    return selected_agent, selected_cap_type


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
