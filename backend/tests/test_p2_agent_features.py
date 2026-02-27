"""Tests for Agent Heartbeat, Bootstrap, and Credential-Pull endpoints."""

import pytest
from httpx import AsyncClient, ASGITransport
from unittest.mock import patch, AsyncMock

from app.main import app
from app.db.engine import async_session
from sqlalchemy import text
from app.api.agent_credentials import create_credential_grant_token


@pytest.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestAgentBootstrapAndHeartbeat:
    @pytest.mark.asyncio
    async def test_bootstrap_agent(self, client):
        resp = await client.get("/api/agents/bootstrap/web_agent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["channel"] == "web_agent"
        assert data["default_pool"] == "web_agent_default"
        assert "recommended_concurrency" in data

    @pytest.mark.asyncio
    async def test_agent_heartbeat(self, client):
        # 1. First register an agent
        agent_id = "heartbeat_test_agent_1"
        
        # Cleanup first if it exists
        await client.delete(f"/api/agents/{agent_id}")
        
        body = {
            "agent_id": agent_id,
            "name": "Heartbeat Test Agent",
            "channel": "desktop",
            "base_url": "http://127.0.0.1:8888",
        }
        register_resp = await client.post("/api/agents", json=body)
        assert register_resp.status_code in [200, 201]

        # 2. Send heartbeat
        hb_body = {
            "agent_id": agent_id,
            "status": "online",
            "cpu_percent": 15.5,
            "memory_percent": 60.1
        }
        hb_resp = await client.post("/api/agents/heartbeat", json=hb_body)
        assert hb_resp.status_code == 200
        assert hb_resp.json()["status"] == "ok"

        # 3. Verify the agent updated its last_heartbeat_at
        agent_resp = await client.get(f"/api/agents/{agent_id}")
        assert agent_resp.status_code == 200
        agent_data = agent_resp.json()
        assert agent_data["last_heartbeat_at"] is not None
        assert agent_data["status"] == "online"


class TestAgentCredentials:
    @pytest.mark.asyncio
    @patch("app.api.agent_credentials.get_secrets_manager")
    async def test_pull_credential_auth_required(self, mock_get_manager, client):
        resp = await client.get("/api/agent-credentials/my_secret")
        assert resp.status_code in (401, 403)  # Missing bearer token
        
    @pytest.mark.asyncio
    @patch("app.api.agent_credentials.get_secrets_manager")
    async def test_pull_credential_success(self, mock_get_manager, client):
        # Mock the secrets manager to return a fake secret
        mock_manager = AsyncMock()
        mock_manager.get_secret.return_value = "super_secret_value"
        mock_get_manager.return_value = mock_manager
        
        # Issue a grant token for run_id "test_run" and secret_name "my_secret"
        token = create_credential_grant_token("test_run", "my_secret")
        
        # Call the endpoint with the Bearer token
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get("/api/agent-credentials/my_secret", headers=headers)
        
        assert resp.status_code == 200
        assert resp.json()["value"] == "super_secret_value"
        mock_manager.get_secret.assert_awaited_once_with("my_secret")

    @pytest.mark.asyncio
    @patch("app.api.agent_credentials.get_secrets_manager")
    async def test_pull_credential_wrong_secret(self, mock_get_manager, client):
        # Issue a grant token for "other_secret"
        token = create_credential_grant_token("test_run", "other_secret")
        
        # Call the endpoint for "my_secret" -> should fail mismatch
        headers = {"Authorization": f"Bearer {token}"}
        resp = await client.get("/api/agent-credentials/my_secret", headers=headers)
        
        assert resp.status_code == 403
        assert "not valid for this secret" in resp.json()["detail"]


class TestAgentRoutingAndAffinity:
    @pytest.mark.asyncio
    async def test_agent_affinity_routing(self):
        from app.runtime.executor_dispatch import _find_capable_agent, _run_agent_affinity, clear_run_affinity
        from app.db.models import AgentInstance
        from unittest.mock import AsyncMock, MagicMock

        # Mock DB session and result
        mock_db = AsyncMock()
        mock_result = MagicMock()
        
        # Create two identical agents in the same pool
        agent1 = AgentInstance(agent_id="web_1", channel="web", status="online", pool_id="pool_1", capabilities="*")
        agent2 = AgentInstance(agent_id="web_2", channel="web", status="online", pool_id="pool_1", capabilities="*")
        mock_result.scalars.return_value.all.return_value = [agent1, agent2]
        
        # db.execute is an async method
        async def mock_execute(*args, **kwargs):
            return mock_result
        mock_db.execute = AsyncMock(side_effect=mock_execute)

        run_id = "test_run_affinity"
        channel = "web"
        clear_run_affinity(run_id)

        # 1. First dispatch establishes affinity
        first_agent, cap_type = await _find_capable_agent(mock_db, channel, "navigate", run_id=run_id)
        assert first_agent is not None
        assert first_agent.agent_id in ["web_1", "web_2"]
        
        # Track which one it picked
        assigned_agent_id = first_agent.agent_id
        assert _run_agent_affinity[f"{run_id}:{channel}"] == assigned_agent_id

        # 2. Second dispatch for SAME run_id MUST return the SAME agent, bypassing round-robin
        second_agent, second_cap_type = await _find_capable_agent(mock_db, channel, "extract", run_id=run_id)
        assert second_agent is not None
        assert second_agent.agent_id == assigned_agent_id

        # 3. Dispatch for DIFFERENT run_id will likely get the OTHER agent due to round-robin
        run_id_2 = "test_run_other"
        third_agent, third_cap_type = await _find_capable_agent(mock_db, channel, "navigate", run_id=run_id_2)
        assert third_agent is not None
        # It should round balance to the other one (though theoretically could be same depending on counter init, 
        # but affinity guarantees run_id_1 stays on assigned_agent_id)
        assert _run_agent_affinity[f"{run_id_2}:{channel}"] == third_agent.agent_id
        
        # 4. Clean up
        clear_run_affinity(run_id)
        clear_run_affinity(run_id_2)
        assert f"{run_id}:{channel}" not in _run_agent_affinity


    @pytest.mark.asyncio
    @patch("app.services.lease_service.try_acquire_lease")
    @patch("app.services.run_service.emit_event")
    async def test_pool_saturation_event(self, mock_emit, mock_try_acquire):
        from app.runtime.node_executors import _acquire_agent_lease
        from app.db.models import AgentInstance
        from unittest.mock import AsyncMock, MagicMock

        mock_db = AsyncMock()
        mock_result = MagicMock()
        
        # Mock an online agent
        agent = AgentInstance(
            agent_id="web_1", channel="web", status="online", 
            resource_key="web_default", pool_id="pool_1", base_url="http://test"
        )
        mock_result.scalars.return_value.first.return_value = agent
        
        async def mock_execute2(*args, **kwargs):
            return mock_result
        mock_db.execute = AsyncMock(side_effect=mock_execute2)

        # Force the lease acquisition to FAIL (simulating full pool)
        # try_acquire_lease is an async function, so it must return an awaitable
        async def mock_fail(*args, **kwargs):
            return None
        mock_try_acquire.side_effect = mock_fail

        run_id = "test_run_saturation"
        
        # Attempt to acquire lease, expect RuntimeError
        try:
            await _acquire_agent_lease(mock_db, agent.base_url, run_id, "node_1", "step_1")
            assert False, "Should have raised RuntimeError for busy resource"
        except RuntimeError as e:
            assert "Resource busy" in str(e)

        # Verify `pool_saturated` event was emitted BEFORE the crash
        mock_emit.assert_awaited_once_with(
            mock_db,
            run_id,
            "pool_saturated",
            node_id="node_1",
            step_id="step_1",
            payload={
                "agent_id": "web_1",
                "channel": "web",
                "resource_key": "web_default",
                "pool_id": "pool_1"
            }
        )

class TestAgentCapabilityParsing:
    def test_has_capability_json_matching(self):
        from app.runtime.executor_dispatch import _has_capability
        from app.db.models import AgentInstance
        import json

        # 1. Test JSON matching tool
        agent_json = AgentInstance(
            agent_id="test_1",
            capabilities=json.dumps([{"name": "my_action", "type": "tool"}])
        )
        has_cap, cap_type = _has_capability(agent_json, "my_action")
        assert has_cap is True
        assert cap_type == "tool"

        # 2. Test JSON matching workflow
        agent_wf = AgentInstance(
            agent_id="test_2",
            capabilities=json.dumps([{"name": "my_workflow", "type": "workflow"}])
        )
        has_cap, cap_type = _has_capability(agent_wf, "my_workflow")
        assert has_cap is True
        assert cap_type == "workflow"

        # 3. Test JSON non-matching
        has_cap, cap_type = _has_capability(agent_json, "other_action")
        assert has_cap is False

        # 4. Test Legacy CSV matching
        agent_csv = AgentInstance(
            agent_id="test_3",
            capabilities="action_a, my_action, action_b"
        )
        has_cap, cap_type = _has_capability(agent_csv, "my_action")
        assert has_cap is True
        assert cap_type == "tool"  # CSV relies on fallback logic which defaults to tool

        # 5. Test empty capabilities in strict mode -> denies by default
        agent_empty = AgentInstance(
            agent_id="test_4",
            capabilities=""
        )
        has_cap, cap_type = _has_capability(agent_empty, "some_action")
        assert has_cap is False
        assert cap_type == "tool"

        # 6. Test wildcard capability
        agent_wildcard = AgentInstance(
            agent_id="test_5",
            capabilities=json.dumps([{"name": "*", "type": "tool"}])
        )
        has_cap, cap_type = _has_capability(agent_wildcard, "any_action_at_all")
        assert has_cap is True
        assert cap_type == "tool"

    def test_has_capability_empty_permissive_mode(self):
        from app.runtime.executor_dispatch import _has_capability
        from app.db.models import AgentInstance
        from app.config import settings

        previous = settings.AGENT_REQUIRE_EXPLICIT_CAPABILITIES
        try:
            object.__setattr__(settings, "AGENT_REQUIRE_EXPLICIT_CAPABILITIES", False)
            agent_empty = AgentInstance(agent_id="test_perm", capabilities="")
            has_cap, cap_type = _has_capability(agent_empty, "some_action")
            assert has_cap is True
            assert cap_type == "tool"
        finally:
            object.__setattr__(settings, "AGENT_REQUIRE_EXPLICIT_CAPABILITIES", previous)
