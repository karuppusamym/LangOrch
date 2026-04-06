"""Shared FastAPI scaffolding for automation agents."""

from __future__ import annotations

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

import httpx
from fastapi import FastAPI, HTTPException, Request

from app.config import settings as orch_settings
from app.contracts.agent_contracts import AgentCapability, AgentExecuteEnvelope, AgentExecuteRequest
from app.contracts.agent_protocol import (
    PROTOCOL_HEADER,
    SIGNATURE_HEADER,
    TENANT_HEADER,
    TIMESTAMP_HEADER,
    TRACE_HEADER,
    build_signed_headers,
    generate_trace_id,
    verify_signed_request,
)
from app.utils.logger import ctx_node_id, ctx_run_id, ctx_step_id, ctx_tenant_id, ctx_trace_id, setup_logger

from automation_agents.runtime_support import DbSessionStore, PolicyDecision, SessionStore, evaluate_policy, validate_json_schema

setup_logger(log_format=os.getenv("LOG_FORMAT", orch_settings.LOG_FORMAT), log_level=os.getenv("LOG_LEVEL", "INFO"))
logger = logging.getLogger("automation_agents.shared")

ExecuteHandler = Callable[[str, dict[str, Any], AgentExecuteRequest], Awaitable[dict[str, Any]]]
HealthProvider = Callable[[], dict[str, Any]]
SessionCloseHandler = Callable[[dict[str, Any]], Awaitable[None]]

_SESSION_ACTIONS = {"open_session", "resume_session", "close_session"}


@dataclass
class AutomationAgentSettings:
    orchestrator_url: str
    agent_id: str
    agent_name: str
    agent_port: int
    channel: str
    pool_id: str
    resource_key: str
    concurrency_limit: int = 1
    description: str = ""
    auto_register: bool = True
    extra_registration: dict[str, Any] = field(default_factory=dict)
    heartbeat_interval_s: int = int(os.getenv("AGENT_HEARTBEAT_INTERVAL_SECONDS", str(orch_settings.AGENT_HEARTBEAT_INTERVAL_SECONDS)))
    signed_communication_secret: str | None = os.getenv("AGENT_SHARED_SECRET", orch_settings.AGENT_SHARED_SECRET or "")
    session_timeout_s: int = int(os.getenv("AGENT_SESSION_TIMEOUT_SECONDS", "1800"))
    protocol_version: str = os.getenv("AGENT_PROTOCOL_VERSION", orch_settings.AGENT_PROTOCOL_VERSION)


def _orchestrator_headers(method: str, path: str, payload: dict[str, Any]) -> dict[str, str]:
    headers = build_signed_headers(
        method,
        path,
        payload,
        secret=(orch_settings.AGENT_SHARED_SECRET or None),
        extra_headers={"X-Agent-ID": payload.get("agent_id", ""), PROTOCOL_HEADER: orch_settings.AGENT_PROTOCOL_VERSION},
    )
    return headers


async def _set_agent_status(
    settings: AutomationAgentSettings,
    capabilities: list[AgentCapability],
    status: str,
) -> None:
    if not settings.auto_register:
        return

    url = f"{settings.orchestrator_url.rstrip('/')}/api/agents/{settings.agent_id}"
    payload: dict[str, Any] = {"status": status}
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            if status == "online":
                register_url = f"{settings.orchestrator_url.rstrip('/')}/api/agents"
                register_payload = {
                    "agent_id": settings.agent_id,
                    "name": settings.agent_name,
                    "channel": settings.channel,
                    "base_url": f"http://127.0.0.1:{settings.agent_port}",
                    "concurrency_limit": settings.concurrency_limit,
                    "resource_key": settings.resource_key,
                    "pool_id": settings.pool_id,
                    "capabilities": [cap.model_dump() for cap in capabilities],
                    **settings.extra_registration,
                }
                response = await client.post(
                    register_url,
                    json=register_payload,
                    headers=_orchestrator_headers("POST", "/api/agents", register_payload),
                )
                response.raise_for_status()
            else:
                response = await client.put(
                    url,
                    json=payload,
                    headers=_orchestrator_headers("PUT", f"/api/agents/{settings.agent_id}", payload),
                )
                response.raise_for_status()
        logger.info("agent_status_update", extra={"agent_id": settings.agent_id, "channel": settings.channel, "status": status})
    except Exception as exc:  # pragma: no cover - best effort registration
        logger.warning("Could not update/register agent status (%s): %s", url, exc)


async def _heartbeat_loop(settings: AutomationAgentSettings) -> None:
    if not settings.auto_register:
        return

    heartbeat_url = f"{settings.orchestrator_url.rstrip('/')}/api/agents/heartbeat"
    interval = max(5, int(settings.heartbeat_interval_s))
    payload = {"agent_id": settings.agent_id, "status": "online"}
    while True:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.post(
                    heartbeat_url,
                    json=payload,
                    headers=_orchestrator_headers("POST", "/api/agents/heartbeat", payload),
                )
                response.raise_for_status()
        except asyncio.CancelledError:  # pragma: no cover
            raise
        except Exception as exc:  # pragma: no cover
            logger.warning("Heartbeat failed for agent '%s': %s", settings.agent_id, exc)
        await asyncio.sleep(interval)


async def _session_cleanup_loop(store: SessionStore | DbSessionStore) -> None:
    while True:
        try:
            await asyncio.sleep(30)
            await store.cleanup_expired()
        except asyncio.CancelledError:  # pragma: no cover
            raise


def _capability_map(capabilities: list[AgentCapability]) -> dict[str, AgentCapability]:
    return {cap.name: cap for cap in capabilities}


async def post_signed_callback(
    callback_url: str,
    payload: dict[str, Any],
    *,
    timeout_s: float = 15.0,
    secret: str | None = None,
    protocol_version: str | None = None,
) -> None:
    parsed = httpx.URL(callback_url)
    path = parsed.path or "/"
    headers = build_signed_headers(
        "POST",
        path,
        payload,
        secret=secret or (orch_settings.AGENT_SHARED_SECRET or None),
        extra_headers={PROTOCOL_HEADER: protocol_version or orch_settings.AGENT_PROTOCOL_VERSION},
    )
    async with httpx.AsyncClient(timeout=timeout_s) as client:
        response = await client.post(callback_url, json=payload, headers=headers)
        response.raise_for_status()


def build_agent_app(
    *,
    title: str,
    version: str,
    settings: AutomationAgentSettings,
    capabilities: list[AgentCapability],
    execute_handler: ExecuteHandler,
    health_provider: HealthProvider | None = None,
    session_store: SessionStore | DbSessionStore | None = None,
    session_close_handler: SessionCloseHandler | None = None,
) -> FastAPI:
    """Build a standard automation-agent FastAPI app."""

    cap_by_name = _capability_map(capabilities)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        await _set_agent_status(settings, capabilities, "online")
        heartbeat_task = asyncio.create_task(_heartbeat_loop(settings))
        cleanup_task = asyncio.create_task(_session_cleanup_loop(session_store)) if session_store else None
        try:
            yield
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            if cleanup_task:
                cleanup_task.cancel()
                try:
                    await cleanup_task
                except asyncio.CancelledError:
                    pass
            await _set_agent_status(settings, capabilities, "offline")

    app = FastAPI(title=title, version=version, lifespan=lifespan)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        payload = {
            "status": "ok",
            "agent_id": settings.agent_id,
            "channel": settings.channel,
            "capability_count": len(capabilities),
            "heartbeat_interval_s": settings.heartbeat_interval_s,
            "protocol_version": settings.protocol_version,
            "policy_enforcement": orch_settings.AGENT_POLICY_ENFORCEMENT,
        }
        if session_store:
            payload["active_sessions"] = await session_store.count()
            payload["session_timeout_s"] = settings.session_timeout_s
            payload["session_backend"] = getattr(session_store, "backend", "memory")
        if health_provider:
            payload.update(health_provider())
        return payload

    @app.get("/capabilities")
    async def capabilities_endpoint() -> dict[str, Any]:
        return {
            "agent_id": settings.agent_id,
            "channel": settings.channel,
            "capabilities": [cap.model_dump() for cap in capabilities],
            "description": settings.description,
            "protocol_version": settings.protocol_version,
            "supports_sessions": session_store is not None,
            "session_backend": getattr(session_store, "backend", None) if session_store is not None else None,
            "policy_enforcement": orch_settings.AGENT_POLICY_ENFORCEMENT,
        }

    @app.post("/execute")
    async def execute(req: AgentExecuteRequest, request: Request) -> dict[str, Any]:
        raw_body = await request.body()
        secret = settings.signed_communication_secret or None
        if secret and not verify_signed_request(
            method=request.method,
            path=request.url.path,
            body=raw_body,
            secret=secret,
            provided_timestamp=request.headers.get(TIMESTAMP_HEADER),
            provided_signature=request.headers.get(SIGNATURE_HEADER),
            ttl_seconds=orch_settings.AGENT_SIGNATURE_TTL_SECONDS,
        ):
            raise HTTPException(status_code=401, detail="Invalid agent request signature")

        action = req.action.strip().lower()
        trace_id = req.trace_id or request.headers.get(TRACE_HEADER) or generate_trace_id()
        tenant_id = req.tenant_id or request.headers.get(TENANT_HEADER)

        token_run = ctx_run_id.set(req.run_id)
        token_node = ctx_node_id.set(req.node_id)
        token_step = ctx_step_id.set(req.step_id)
        token_tenant = ctx_tenant_id.set(tenant_id)
        token_trace = ctx_trace_id.set(trace_id)
        started_at = time.time()
        capability = cap_by_name.get(action)
        policy: PolicyDecision | None = None
        try:
            if action in _SESSION_ACTIONS and not session_store:
                raise ValueError("This agent does not support sessions")

            if action == "open_session":
                if capability and capability.input_schema:
                    validate_json_schema(capability.input_schema, req.params, f"{action} input")
                session_seed = {
                    **req.params,
                    "run_id": req.run_id,
                    "tenant_id": tenant_id,
                    "user_id": req.user_id,
                }
                entry = await session_store.create(session_seed)  # type: ignore[union-attr]
                session_result = {"session_id": entry.session_id, "expires_at": entry.expires_at, "created_at": entry.created_at}
                if capability and capability.output_schema:
                    validate_json_schema(capability.output_schema, session_result, f"{action} output")
                envelope = AgentExecuteEnvelope(
                    status="success",
                    result=session_result,
                    trace_id=trace_id,
                    duration_ms=int((time.time() - started_at) * 1000),
                    protocol_version=settings.protocol_version,
                )
                return envelope.model_dump(exclude_none=True)

            if action == "resume_session":
                session_id = req.session_id or req.params.get("session_id")
                if not session_id:
                    raise ValueError("resume_session requires session_id")
                resume_params = {**req.params, "session_id": str(session_id)}
                if capability and capability.input_schema:
                    validate_json_schema(capability.input_schema, resume_params, f"{action} input")
                entry = await session_store.get(str(session_id))  # type: ignore[union-attr]
                if entry is None:
                    raise ValueError(f"Session '{session_id}' not found")
                session_result = entry.snapshot()
                if capability and capability.output_schema:
                    validate_json_schema(capability.output_schema, session_result, f"{action} output")
                envelope = AgentExecuteEnvelope(
                    status="success",
                    result=session_result,
                    trace_id=trace_id,
                    duration_ms=int((time.time() - started_at) * 1000),
                    protocol_version=settings.protocol_version,
                )
                return envelope.model_dump(exclude_none=True)

            if action == "close_session":
                session_id = req.session_id or req.params.get("session_id")
                if not session_id:
                    raise ValueError("close_session requires session_id")
                close_params = {**req.params, "session_id": str(session_id)}
                if capability and capability.input_schema:
                    validate_json_schema(capability.input_schema, close_params, f"{action} input")
                entry = await session_store.close(str(session_id))  # type: ignore[union-attr]
                if entry is None:
                    raise ValueError(f"Session '{session_id}' not found")
                if session_close_handler:
                    await session_close_handler({"session_id": str(session_id), **entry.data})
                session_result = {"session_id": str(session_id), "closed": True}
                if capability and capability.output_schema:
                    validate_json_schema(capability.output_schema, session_result, f"{action} output")
                envelope = AgentExecuteEnvelope(
                    status="success",
                    result=session_result,
                    trace_id=trace_id,
                    duration_ms=int((time.time() - started_at) * 1000),
                    protocol_version=settings.protocol_version,
                )
                return envelope.model_dump(exclude_none=True)

            merged_params = dict(req.params)
            session_id = req.session_id or merged_params.get("session_id")
            if session_store and session_id:
                entry = await session_store.get(str(session_id))
                if entry is None:
                    raise ValueError(f"Session '{session_id}' not found")
                merged_params = {**entry.data, **merged_params, "session_id": str(session_id)}

            if capability and capability.input_schema:
                validate_json_schema(capability.input_schema, merged_params, f"{action} input")

            policy = evaluate_policy(capability, merged_params, req)
            if not policy.allowed:
                raise PermissionError("; ".join(policy.reasons))

            result = await execute_handler(action, merged_params, req)
            if capability and capability.output_schema:
                validate_json_schema(capability.output_schema, result, f"{action} output")

            duration_ms = int((time.time() - started_at) * 1000)
            provider = result.get("provider") if isinstance(result, dict) else None
            warnings = policy.warnings if policy else []
            envelope = AgentExecuteEnvelope(
                status="success",
                result=result,
                trace_id=trace_id,
                provider=provider,
                duration_ms=duration_ms,
                warnings=warnings,
                policy=policy.as_dict() if policy else None,
                protocol_version=settings.protocol_version,
            )
            logger.info(
                "agent_execute_success",
                extra={
                    "agent_id": settings.agent_id,
                    "channel": settings.channel,
                    "action": action,
                    "duration_ms": duration_ms,
                    "provider": provider,
                    "trace_id": trace_id,
                    "session_id": session_id,
                },
            )
            return envelope.model_dump(exclude_none=True)
        except Exception as exc:
            duration_ms = int((time.time() - started_at) * 1000)
            logger.exception("Agent action failed: %s", action)
            envelope = AgentExecuteEnvelope(
                status="error",
                error=f"{type(exc).__name__}: {exc}",
                error_code=type(exc).__name__,
                retryable=False,
                trace_id=trace_id,
                duration_ms=duration_ms,
                policy=policy.as_dict() if policy else None,
                protocol_version=settings.protocol_version,
            )
            return envelope.model_dump(exclude_none=True)
        finally:
            ctx_run_id.reset(token_run)
            ctx_node_id.reset(token_node)
            ctx_step_id.reset(token_step)
            ctx_tenant_id.reset(token_tenant)
            ctx_trace_id.reset(token_trace)

    return app
