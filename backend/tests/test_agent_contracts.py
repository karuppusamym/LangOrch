from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.contracts.action_contracts import get_channel_for_action, normalize_action_name
from app.contracts.swarm_contracts import verify_swarm_output
from app.db.models import AgentInstance
from app.main import app
from app.runtime.executor_dispatch import _has_capability
from app.services.agent_contract_service import run_agent_contract_tests


def _load_swarm_agent_module():
    module_path = Path(__file__).resolve().parents[1] / "automation_agents" / "swarm_agent.py"
    spec = importlib.util.spec_from_file_location("swarm_agent_contract_test", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec is not None and spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.mark.asyncio
async def test_action_contract_normalizes_aliases_and_prefixes():
    assert normalize_action_name("browser.navigate") == "navigate"
    assert normalize_action_name("navigate_to") == "navigate"
    assert get_channel_for_action("browser.navigate") == "web"
    assert get_channel_for_action("navigate_to") == "web"


def test_dispatch_capability_matching_uses_shared_action_normalization():
    agent = AgentInstance(
        agent_id="web_1",
        channel="web",
        status="online",
        capabilities=json.dumps([{"name": "navigate", "type": "tool"}]),
    )
    has_cap, cap_type = _has_capability(agent, "browser.navigate")
    assert has_cap is True
    assert cap_type == "tool"


def test_verify_swarm_failure_analysis_requires_safe_actions_and_consistent_guidance():
    valid = verify_swarm_output(
        "swarm.failure_analysis",
        {
            "swarm_result": {
                "goal": "Analyze failed run",
                "probable_root_cause": "contract_mismatch",
                "retry_recommended": False,
                "escalation_recommended": True,
                "compensation_recommended": False,
                "safe_next_actions": ["run_contract_test"],
                "confidence": 0.91,
                "evidence": [{"source": "classifier", "detail": "Schema mismatch"}],
                "verifier_summary": "Retry is blocked until the contract issue is fixed.",
            }
        },
    )
    assert valid["swarm_result"]["probable_root_cause"] == "contract_mismatch"

    with pytest.raises(ValueError, match="retry and compensation"):
        verify_swarm_output(
            "swarm.failure_analysis",
            {
                "swarm_result": {
                    "goal": "Analyze failed run",
                    "probable_root_cause": "partial_side_effect",
                    "retry_recommended": True,
                    "escalation_recommended": True,
                    "compensation_recommended": True,
                    "safe_next_actions": ["inspect_side_effects"],
                    "confidence": 0.87,
                    "evidence": [{"source": "classifier", "detail": "Duplicate write"}],
                    "verifier_summary": "Conflicting guidance.",
                }
            },
        )


@pytest.mark.asyncio
async def test_swarm_agent_exposes_failure_analysis_sync_execution():
    swarm_agent = _load_swarm_agent_module()
    transport = ASGITransport(app=swarm_agent.app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/execute",
            json={
                "action": "swarm.failure_analysis",
                "params": {
                    "context": {
                        "error_message": "HTTP 503 timeout from downstream dependency",
                        "timeline": ["step_started", "step_failed"],
                    }
                },
                "run_id": "run1",
                "node_id": "node1",
                "step_id": "step1",
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["result"]["swarm_result"]["probable_root_cause"] == "transient_dependency_failure"
    assert payload["result"]["swarm_result"]["safe_next_actions"]


@pytest.mark.asyncio
async def test_agent_contract_service_simulate_covers_declared_capabilities():
    agent = AgentInstance(
        agent_id="sim-agent",
        channel="swarm",
        status="online",
        base_url="http://agent.local",
        capabilities=json.dumps(
            [
                {"name": "swarm.failure_analysis", "type": "workflow"},
                {"name": "navigate", "type": "tool"},
            ]
        ),
    )

    result = await run_agent_contract_tests(agent, mode="simulate")
    assert result.total == 2
    assert result.failed == 0
    assert result.passed == 2


@pytest.mark.asyncio
async def test_agent_contract_service_replay_validates_agent_responses(monkeypatch):
    async def fake_execute(self, action, params, run_id, node_id, step_id):
        if action == "swarm.failure_analysis":
            return {
                "swarm_result": {
                    "goal": "Analyze failed run",
                    "probable_root_cause": "transient_dependency_failure",
                    "retry_recommended": True,
                    "escalation_recommended": False,
                    "compensation_recommended": False,
                    "safe_next_actions": ["retry_from_last_safe_checkpoint"],
                    "confidence": 0.88,
                    "evidence": [{"source": "classifier", "detail": "Timeout detected"}],
                    "verifier_summary": "Retry is safe because failure looks transient.",
                }
            }
        return {"ok": True, "action": action, "params": params}

    async def fake_close(self):
        return None

    monkeypatch.setattr("app.services.agent_contract_service.AgentClient.execute_action", fake_execute)
    monkeypatch.setattr("app.services.agent_contract_service.AgentClient.close", fake_close)

    agent = AgentInstance(
        agent_id="replay-agent",
        channel="swarm",
        status="online",
        base_url="http://agent.local",
        capabilities=json.dumps(
            [
                {"name": "swarm.failure_analysis", "type": "workflow"},
                {"name": "navigate", "type": "tool"},
            ]
        ),
    )

    result = await run_agent_contract_tests(agent, mode="replay")
    assert result.total == 2
    assert result.failed == 0
    assert result.passed == 2


@pytest.mark.asyncio
async def test_agent_contract_test_api_runs_simulation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        agent_id = "contract-api-agent"
        register_resp = await client.post(
            "/api/agents",
            json={
                "agent_id": agent_id,
                "name": "Contract API Agent",
                "channel": "swarm",
                "base_url": "http://agent.local",
                "capabilities": [
                    {"name": "swarm.failure_analysis", "type": "workflow"},
                    {"name": "navigate", "type": "tool"},
                ],
            },
        )
        assert register_resp.status_code in (200, 201)

        response = await client.post(
            f"/api/agents/{agent_id}/contract-test",
            json={"mode": "simulate"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["agent_id"] == agent_id
    assert payload["failed"] == 0
    assert payload["passed"] == 2
