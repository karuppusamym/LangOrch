"""Agent HTTP client connector for dispatching actions to registered agents."""

from __future__ import annotations

import logging
from typing import Any

import httpx
from opentelemetry import trace
from pydantic import ValidationError

from app.config import settings
from app.contracts.agent_contracts import AgentExecuteEnvelope
from app.contracts.agent_protocol import (
    ATTEMPT_HEADER,
    IDEMPOTENCY_HEADER,
    LEASE_HEADER,
    NODE_HEADER,
    PROTOCOL_HEADER,
    RUN_HEADER,
    STEP_HEADER,
    TENANT_HEADER,
    TRACE_HEADER,
    build_signed_headers,
    generate_trace_id,
)
from app.utils.logger import ctx_trace_id

logger = logging.getLogger("langorch.connectors.agent")


class AgentClient:
    """
    Communicates with a registered agent instance over HTTP.

    Protocol contract:
      POST {agent_url}/execute
      Body: {
        "action": "click_element",
        "params": {...},
        "run_id": "...",
        "node_id": "...",
        "step_id": "..."
      }
      Response: {
        "status": "success" | "error",
        "result": {...},
        "error": "..." (optional)
      }
    """

    def __init__(self, agent_url: str, timeout: float = 120.0):
        self.agent_url = agent_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.agent_url, timeout=self.timeout)

    async def execute_action(
        self,
        action: str,
        params: dict[str, Any],
        run_id: str,
        node_id: str,
        step_id: str,
        *,
        attempt: int = 1,
        idempotency_key: str | None = None,
        timeout_ms: int | None = None,
        trace_id: str | None = None,
        tenant_id: str | None = None,
        user_id: str | None = None,
        approval_id: str | None = None,
        session_id: str | None = None,
        lease_id: str | None = None,
        callback_url: str | None = None,
        dry_run: bool = False,
        priority: int | None = None,
        include_envelope_meta: bool = False,
    ) -> dict[str, Any]:
        """Send an action to the agent for execution."""
        active_span = trace.get_current_span().get_span_context()
        resolved_trace_id = trace_id or (trace.format_trace_id(active_span.trace_id) if active_span.is_valid else None) or ctx_trace_id.get() or generate_trace_id()
        payload = {
            "action": action,
            "params": params,
            "run_id": run_id,
            "node_id": node_id,
            "step_id": step_id,
            "attempt": attempt,
            "idempotency_key": idempotency_key,
            "timeout_ms": timeout_ms,
            "trace_id": resolved_trace_id,
            "tenant_id": tenant_id,
            "user_id": user_id,
            "approval_id": approval_id,
            "session_id": session_id,
            "lease_id": lease_id,
            "callback_url": callback_url,
            "dry_run": dry_run,
            "priority": priority,
        }
        # Propagate correlation headers so agent logs can be linked to LangOrch run
        correlation_headers = {
            RUN_HEADER: run_id,
            NODE_HEADER: node_id,
            STEP_HEADER: step_id,
            TRACE_HEADER: resolved_trace_id,
            ATTEMPT_HEADER: str(attempt),
            PROTOCOL_HEADER: settings.AGENT_PROTOCOL_VERSION,
        }
        if idempotency_key:
            correlation_headers[IDEMPOTENCY_HEADER] = idempotency_key
        if tenant_id:
            correlation_headers[TENANT_HEADER] = tenant_id
        if lease_id:
            correlation_headers[LEASE_HEADER] = lease_id
        headers = build_signed_headers(
            "POST",
            "/execute",
            payload,
            secret=(settings.AGENT_SHARED_SECRET or None),
            extra_headers=correlation_headers,
        )
        logger.info("Agent call: %s action=%s run=%s trace=%s", self.agent_url, action, run_id, resolved_trace_id)

        try:
            resp = await self._client.post("/execute", json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()

            envelope: AgentExecuteEnvelope | None = None
            if settings.AGENT_STRICT_RESPONSE_SCHEMA:
                try:
                    envelope = AgentExecuteEnvelope.model_validate(data)
                except ValidationError as exc:
                    raise AgentActionError(
                        action,
                        f"Invalid agent response schema: {exc.errors()[0].get('msg', 'validation error')}",
                    ) from exc
            else:
                # Backward-compatible mode for legacy agents
                if isinstance(data, dict) and "status" in data:
                    try:
                        envelope = AgentExecuteEnvelope.model_validate(data)
                    except ValidationError:
                        envelope = None
                elif isinstance(data, dict):
                    logger.warning(
                        "Legacy agent response (missing status envelope) accepted for action=%s run=%s",
                        action,
                        run_id,
                    )
                    return data.get("result", data)

            if envelope and envelope.status == "error":
                raise AgentActionError(action, envelope.error or "Unknown agent error")

            if envelope:
                if include_envelope_meta:
                    return {
                        "result": envelope.result if envelope.result is not None else {},
                        "meta": {
                            "provider": envelope.provider,
                            "warnings": envelope.warnings,
                            "policy": envelope.policy,
                            "protocol_version": envelope.protocol_version,
                            "trace_id": envelope.trace_id,
                            "duration_ms": envelope.duration_ms,
                            "status": envelope.status,
                        },
                    }
                return envelope.result if envelope.result is not None else {}

            # Permissive fallback (strict mode disabled and unknown response shape)
            if isinstance(data, dict):
                return data.get("result", data)
            raise AgentActionError(action, "Agent response must be a JSON object")

        except httpx.HTTPStatusError as exc:
            raise AgentActionError(action, f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise AgentActionError(action, str(exc)) from exc

    async def health_check(self) -> bool:
        """Check if the agent instance is healthy."""
        try:
            resp = await self._client.get("/health")
            return resp.status_code == 200
        except Exception:
            return False

    async def close(self):
        await self._client.aclose()


class AgentActionError(Exception):
    def __init__(self, action: str, message: str):
        self.action = action
        super().__init__(f"Agent action '{action}' failed: {message}")
