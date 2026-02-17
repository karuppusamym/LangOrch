"""Agent HTTP client connector for dispatching actions to registered agents."""

from __future__ import annotations

import logging
from typing import Any

import httpx

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
    ) -> dict[str, Any]:
        """Send an action to the agent for execution."""
        payload = {
            "action": action,
            "params": params,
            "run_id": run_id,
            "node_id": node_id,
            "step_id": step_id,
        }
        logger.info("Agent call: %s action=%s", self.agent_url, action)

        try:
            resp = await self._client.post("/execute", json=payload)
            resp.raise_for_status()
            data = resp.json()

            if data.get("status") == "error":
                raise AgentActionError(action, data.get("error", "Unknown agent error"))

            return data.get("result", data)

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
