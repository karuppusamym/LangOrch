"""MCP (Model Context Protocol) client connector."""

from __future__ import annotations

import logging
from typing import Any

import httpx

logger = logging.getLogger("langorch.connectors.mcp")


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
                raise MCPToolError(tool_name, data.get("error", "Unknown MCP error"))

            return data.get("result", data)

        except httpx.HTTPStatusError as exc:
            raise MCPToolError(tool_name, f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
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
