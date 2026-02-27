"""Agent HTTP client connector for dispatching actions to registered agents."""

from __future__ import annotations

import logging
from typing import Any
from typing import Literal

import httpx
from pydantic import BaseModel, ValidationError

from app.config import settings

logger = logging.getLogger("langorch.connectors.agent")


class AgentExecuteEnvelope(BaseModel):
    status: Literal["success", "error"]
    result: Any | None = None
    error: str | None = None


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
    ) -> dict[str, Any]:
        """Send an action to the agent for execution."""
        payload = {
            "action": action,
            "params": params,
            "run_id": run_id,
            "node_id": node_id,
            "step_id": step_id,
        }
        # Propagate correlation headers so agent logs can be linked to LangOrch run
        correlation_headers = {
            "X-Run-ID": run_id,
            "X-Node-ID": node_id,
            "X-Step-ID": step_id,
        }
        logger.info("Agent call: %s action=%s run=%s", self.agent_url, action, run_id)

        try:
            resp = await self._client.post("/execute", json=payload, headers=correlation_headers)
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
