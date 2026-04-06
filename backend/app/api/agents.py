"""Agent instances API router."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import get_db
from app.db.models import AgentInstance, ResourceLease, RunEvent
from app.schemas.agents import (
    AgentBootstrapOut,
    AgentContractTestOut,
    AgentContractTestRequest,
    AgentHeartbeat,
    AgentInstanceCreate,
    AgentInstanceOut,
    AgentInstanceUpdate,
)
from app.auth import require_role
from app.auth.deps import Principal
from app.contracts.agent_contracts import parse_agent_capabilities, serialize_agent_capabilities
from app.contracts.agent_protocol import SIGNATURE_HEADER, TIMESTAMP_HEADER, verify_signed_request
from app.services.agent_contract_service import run_agent_contract_tests

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
            caps = parse_agent_capabilities(data.get("capabilities"))
            if caps:
                return [cap.model_dump() for cap in caps]
    except Exception as exc:  # pragma: no cover
        logger.debug("Could not probe capabilities from %s: %s", url, exc)
    return None


async def _verify_signed_agent_request(request: Request, *, required: bool = False) -> None:
    secret = settings.AGENT_SHARED_SECRET or None
    if not secret:
        return
    provided_signature = request.headers.get(SIGNATURE_HEADER)
    provided_timestamp = request.headers.get(TIMESTAMP_HEADER)
    if not provided_signature and not provided_timestamp:
        if required:
            raise HTTPException(status_code=401, detail="Missing agent request signature")
        return
    body = await request.body()
    if not verify_signed_request(
        method=request.method,
        path=request.url.path,
        body=body,
        secret=secret,
        provided_timestamp=provided_timestamp,
        provided_signature=provided_signature,
        ttl_seconds=settings.AGENT_SIGNATURE_TTL_SECONDS,
    ):
        raise HTTPException(status_code=401, detail="Invalid agent request signature")


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
async def register_agent(
    body: AgentInstanceCreate,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_role("operator")),
):
    await _verify_signed_agent_request(request, required=False)
    agent_id = body.agent_id or f"{body.channel}_{body.name.replace(' ', '_').lower()}"
    resource_key = body.resource_key or f"{body.channel}_default"
    now = datetime.now(timezone.utc)

    # Auto-discover capabilities from the live agent if none provided
    resolved_caps = body.capabilities
    if not resolved_caps:
        resolved_caps = await _probe_capabilities(body.base_url)

    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    existing = result.scalar_one_or_none()
    serialized_caps = serialize_agent_capabilities(resolved_caps)

    if existing:
        existing.name = body.name
        existing.channel = body.channel
        existing.base_url = body.base_url
        existing.concurrency_limit = body.concurrency_limit
        existing.resource_key = resource_key
        existing.pool_id = body.pool_id
        existing.capabilities = serialized_caps
        existing.status = "online"
        existing.last_heartbeat_at = now
        existing.updated_at = now
        await db.flush()
        await db.refresh(existing)
        response.status_code = 200
        return existing

    inst = AgentInstance(
        agent_id=agent_id,
        name=body.name,
        channel=body.channel,
        base_url=body.base_url,
        concurrency_limit=body.concurrency_limit,
        resource_key=resource_key,
        pool_id=body.pool_id,
        capabilities=serialized_caps,
        last_heartbeat_at=now,
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
                "stale_agent_count": 0,
            }
        p = pools[key]
        p["agent_count"] += 1
        p["status_breakdown"][agent.status] = p["status_breakdown"].get(agent.status, 0) + 1
        p["concurrency_limit_total"] += agent.concurrency_limit
        p["active_leases"] += active_by_key.get(agent.resource_key, 0)
        if agent.last_heartbeat_at:
            heartbeat_ts = agent.last_heartbeat_at
            if getattr(heartbeat_ts, "tzinfo", None) is not None:
                heartbeat_ts = heartbeat_ts.astimezone(timezone.utc).replace(tzinfo=None)
            if (now - heartbeat_ts).total_seconds() >= settings.AGENT_STALE_AFTER_SECONDS:
                p["stale_agent_count"] += 1
        if agent.circuit_open_at:
            circuit_ts = agent.circuit_open_at
            if getattr(circuit_ts, "tzinfo", None) is not None:
                circuit_ts = circuit_ts.astimezone(timezone.utc).replace(tzinfo=None)
            elapsed = (now - circuit_ts).total_seconds()
            if elapsed < 300:
                p["circuit_open_count"] += 1

    # Compute available capacity
    for p in pools.values():
        p["available_capacity"] = max(0, p["concurrency_limit_total"] - p["active_leases"])

    return list(pools.values())


@router.get("/operations/recent")
async def get_recent_agent_operations(limit: int = Query(20, ge=1, le=100), db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(RunEvent)
        .where(
            RunEvent.event_type.in_(
                [
                    "agent_execution_audit",
                    "agent_policy_warning",
                    "agent_policy_denied",
                    "workflow_dispatch_failure",
                    "step_timeout",
                ]
            )
        )
        .order_by(RunEvent.ts.desc())
        .limit(limit)
    )
    events = []
    for event in result.scalars().all():
        payload = None
        if event.payload_json:
            try:
                payload = json.loads(event.payload_json)
            except json.JSONDecodeError:
                payload = {"raw": event.payload_json}
        events.append(
            {
                "event_id": event.event_id,
                "run_id": event.run_id,
                "event_type": event.event_type,
                "node_id": event.node_id,
                "step_id": event.step_id,
                "ts": event.ts,
                "payload": payload or {},
            }
        )
    return events


@router.get("/{agent_id}", response_model=AgentInstanceOut)
async def get_agent(agent_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}", response_model=AgentInstanceOut)
async def update_agent(agent_id: str, body: AgentInstanceUpdate, request: Request, db: AsyncSession = Depends(get_db), _principal: Principal = Depends(require_role("operator"))):
    await _verify_signed_agent_request(request, required=False)
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
        agent.capabilities = serialize_agent_capabilities(body.capabilities)
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

    agent.capabilities = serialize_agent_capabilities(caps)
    agent.updated_at = datetime.now(timezone.utc)
    await db.flush()
    await db.refresh(agent)
    logger.info("Synced capabilities for agent '%s': %s", agent_id, caps)
    return agent


@router.post("/{agent_id}/contract-test", response_model=AgentContractTestOut)
async def contract_test_agent(
    agent_id: str,
    body: AgentContractTestRequest,
    db: AsyncSession = Depends(get_db),
    _principal: Principal = Depends(require_role("operator")),
):
    """Run simulation or live replay contract tests for a registered agent."""
    result = await db.execute(select(AgentInstance).where(AgentInstance.agent_id == agent_id))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    try:
        return await run_agent_contract_tests(
            agent,
            mode=body.mode,
            selected_capabilities=body.capabilities,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
async def agent_heartbeat(body: AgentHeartbeat, request: Request, db: AsyncSession = Depends(get_db)):
    """Receive heartbeat from an active agent instance."""
    await _verify_signed_agent_request(request, required=bool(settings.AGENT_SHARED_SECRET))
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
