from unittest.mock import AsyncMock, MagicMock

import pytest

from app.config import settings
from app.connectors.agent_client import AgentActionError, AgentClient


def _make_http_response(payload: dict) -> MagicMock:
    """Build a synchronous httpx-like response mock.

    httpx.Response.raise_for_status() and .json() are both synchronous methods,
    so the response object itself must NOT be an AsyncMock.
    """
    resp = MagicMock()
    resp.raise_for_status.return_value = None  # synchronous, returns None on 2xx
    resp.json.return_value = payload          # synchronous
    return resp


@pytest.mark.asyncio
async def test_agent_client_rejects_invalid_schema_in_strict_mode():
    prev = settings.AGENT_STRICT_RESPONSE_SCHEMA
    object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", True)
    try:
        client = AgentClient("http://agent.local")
        client._client.post = AsyncMock(return_value=_make_http_response(
            {"result": {"ok": True}}  # missing status → schema error
        ))

        with pytest.raises(AgentActionError, match="Invalid agent response schema"):
            await client.execute_action("click", {}, "run1", "node1", "step1")

        await client.close()
    finally:
        object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", prev)


@pytest.mark.asyncio
async def test_agent_client_accepts_legacy_response_when_permissive():
    prev = settings.AGENT_STRICT_RESPONSE_SCHEMA
    object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", False)
    try:
        client = AgentClient("http://agent.local")
        client._client.post = AsyncMock(return_value=_make_http_response(
            {"foo": "bar"}  # legacy plain payload without status key
        ))

        result = await client.execute_action("click", {}, "run1", "node1", "step1")
        assert result == {"foo": "bar"}

        await client.close()
    finally:
        object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", prev)


@pytest.mark.asyncio
async def test_agent_client_handles_error_status_envelope():
    # Uses strict mode (default True) — a well-formed error envelope should raise.
    prev = settings.AGENT_STRICT_RESPONSE_SCHEMA
    object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", True)
    try:
        client = AgentClient("http://agent.local")
        client._client.post = AsyncMock(return_value=_make_http_response(
            {"status": "error", "error": "boom"}
        ))

        with pytest.raises(AgentActionError, match="boom"):
            await client.execute_action("click", {}, "run1", "node1", "step1")

        await client.close()
    finally:
        object.__setattr__(settings, "AGENT_STRICT_RESPONSE_SCHEMA", prev)
