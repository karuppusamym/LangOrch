"""MCP (Model Context Protocol) client connector.

Circuit breaker: after ``_MCP_CIRCUIT_THRESHOLD`` consecutive failures the
client short-circuits with ``MCPToolError`` until ``_MCP_CIRCUIT_RESET_SECONDS``
have elapsed, preventing cascading failures against an unhealthy MCP server.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

import httpx

logger = logging.getLogger("langorch.connectors.mcp")

# ── Circuit breaker state (module-level, process-scoped) ──────────────────────
_mcp_consecutive_failures: int = 0
_mcp_circuit_open_at: datetime | None = None
_MCP_CIRCUIT_THRESHOLD: int = 5
_MCP_CIRCUIT_RESET_SECONDS: int = 300


def _check_mcp_circuit() -> None:
    """Raise immediately if the MCP circuit breaker is open."""
    global _mcp_circuit_open_at
    if _mcp_circuit_open_at is None:
        return
    elapsed = (datetime.now(timezone.utc) - _mcp_circuit_open_at).total_seconds()
    if elapsed < _MCP_CIRCUIT_RESET_SECONDS:
        raise MCPToolError(
            "mcp",
            f"MCP circuit breaker open (failed {_MCP_CIRCUIT_THRESHOLD}× "
            f"consecutively; resets in {_MCP_CIRCUIT_RESET_SECONDS - int(elapsed)}s)",
        )
    # Reset period elapsed — close the circuit
    _mcp_circuit_open_at = None


def _record_mcp_success() -> None:
    global _mcp_consecutive_failures, _mcp_circuit_open_at
    _mcp_consecutive_failures = 0
    _mcp_circuit_open_at = None


def _record_mcp_failure() -> None:
    global _mcp_consecutive_failures, _mcp_circuit_open_at
    _mcp_consecutive_failures += 1
    if _mcp_consecutive_failures >= _MCP_CIRCUIT_THRESHOLD:
        _mcp_circuit_open_at = datetime.now(timezone.utc)
        logger.warning(
            "MCP circuit breaker OPENED after %d consecutive failures",
            _mcp_consecutive_failures,
        )


def reset_mcp_circuit_breaker() -> None:
    """Reset MCP circuit breaker state (useful for tests)."""
    global _mcp_consecutive_failures, _mcp_circuit_open_at
    _mcp_consecutive_failures = 0
    _mcp_circuit_open_at = None


class MCPClient:
    """
    Communicates with an MCP-compliant tool server.

    Protocol contract:
      POST {base_url}/tools/{tool_name}
      Body: { "arguments": {...} }
      Response: { "result": {...}, "isError": false }
    """

    def __init__(self, base_url: str, timeout: float = 30.0):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, Any],
        run_id: str = "",
        node_id: str = "",
        step_id: str = "",
    ) -> dict[str, Any]:
        """Invoke an MCP tool and return the result dict."""
        # Circuit breaker pre-check
        _check_mcp_circuit()

        url = f"/tools/{tool_name}"
        logger.info("MCP call: %s %s run=%s", url, list(arguments.keys()), run_id)
        correlation_headers: dict[str, str] = {}
        if run_id:
            correlation_headers["X-Run-ID"] = run_id
        if node_id:
            correlation_headers["X-Node-ID"] = node_id
        if step_id:
            correlation_headers["X-Step-ID"] = step_id

        try:
            resp = await self._client.post(url, json={"arguments": arguments}, headers=correlation_headers)
            resp.raise_for_status()
            data = resp.json()

            if data.get("isError"):
                _record_mcp_failure()
                raise MCPToolError(tool_name, data.get("error", "Unknown MCP error"))

            _record_mcp_success()
            return data.get("result", data)

        except httpx.HTTPStatusError as exc:
            _record_mcp_failure()
            raise MCPToolError(tool_name, f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            _record_mcp_failure()
            raise MCPToolError(tool_name, str(exc)) from exc

    async def list_tools(self) -> list[dict[str, Any]]:
        """List available tools from the MCP server."""
        try:
            resp = await self._client.get("/tools")
            resp.raise_for_status()
            return resp.json().get("tools", [])
        except Exception:
            logger.exception("Failed to list MCP tools")
            return []

    async def close(self):
        await self._client.aclose()


class MCPToolError(Exception):
    def __init__(self, tool_name: str, message: str):
        self.tool_name = tool_name
        super().__init__(f"MCP tool '{tool_name}' failed: {message}")
