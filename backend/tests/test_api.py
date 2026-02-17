"""Tests for API endpoints using FastAPI TestClient."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient, ASGITransport

from app.main import app


def _uid() -> str:
    """Return a short unique suffix for test isolation."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestHealthEndpoint:
    @pytest.mark.asyncio
    async def test_health_returns_ok(self, client):
        resp = await client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


class TestMetricsEndpoint:
    @pytest.mark.asyncio
    async def test_metrics_summary(self, client):
        resp = await client.get("/api/runs/metrics/summary")
        assert resp.status_code == 200
        data = resp.json()
        assert "counters" in data
        assert "histograms" in data


class TestProceduresAPI:
    @pytest.mark.asyncio
    async def test_list_procedures(self, client):
        resp = await client.get("/api/procedures")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_import_procedure(self, client):
        pid = f"api_test_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "description": "Test procedure via API",
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [
                            {"step_id": "s1", "action": "log", "message": "hello"}
                        ],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        body = {"ckp_json": ckp}
        resp = await client.post("/api/procedures", json=body)
        assert resp.status_code == 201
        data = resp.json()
        assert data["procedure_id"] == pid
        assert data["version"] == "1.0.0"

    @pytest.mark.asyncio
    async def test_import_and_list_procedure(self, client):
        pid = f"list_test_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "2.0.0",
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "a",
                "nodes": {"a": {"type": "terminate", "status": "success"}},
            },
        }
        body = {"ckp_json": ckp}
        await client.post("/api/procedures", json=body)
        
        resp = await client.get("/api/procedures")
        assert resp.status_code == 200
        procs = resp.json()
        ids = [p["procedure_id"] for p in procs]
        assert pid in ids

    @pytest.mark.asyncio
    async def test_get_procedure_not_found(self, client):
        resp = await client.get("/api/procedures/nonexistent/1.0.0")
        assert resp.status_code == 404


class TestRunsAPI:
    @pytest.mark.asyncio
    async def test_list_runs(self, client):
        resp = await client.get("/api/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_get_run_not_found(self, client):
        resp = await client.get("/api/runs/nonexistent-run-id")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_run_diagnostics_not_found(self, client):
        resp = await client.get("/api/runs/nonexistent-run-id/diagnostics")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_run_checkpoints_not_found(self, client):
        resp = await client.get("/api/runs/nonexistent-run-id/checkpoints")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cancel_run_not_found(self, client):
        resp = await client.post("/api/runs/nonexistent/cancel")
        assert resp.status_code == 404


class TestAgentsAPI:
    @pytest.mark.asyncio
    async def test_list_agents(self, client):
        resp = await client.get("/api/agents")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    @pytest.mark.asyncio
    async def test_register_agent(self, client):
        agent_id = f"test-agent-{_uid()}"
        body = {
            "agent_id": agent_id,
            "name": "Test Agent",
            "channel": "api",
            "base_url": "http://127.0.0.1:9999",
            "resource_key": "test_resource",
            "concurrency_limit": 3,
        }
        resp = await client.post("/api/agents", json=body)
        assert resp.status_code in [200, 201]

    @pytest.mark.asyncio
    async def test_agent_not_found(self, client):
        resp = await client.get("/api/agents/nonexistent-agent-id")
        assert resp.status_code == 404


class TestCreateAndRunWorkflow:
    """Integration test: import a procedure, create a run."""

    @pytest.mark.asyncio
    async def test_create_run_from_procedure(self, client):
        pid = f"run_test_{_uid()}"
        # Import procedure
        ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [
                            {"step_id": "s1", "action": "log", "message": "test"}
                        ],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        import_body = {"ckp_json": ckp}
        import_resp = await client.post("/api/procedures", json=import_body)
        assert import_resp.status_code == 201

        # Create a run
        run_body = {
            "procedure_id": pid,
            "procedure_version": "1.0.0",
            "input_vars": {},
        }
        run_resp = await client.post("/api/runs", json=run_body)
        assert run_resp.status_code == 201
        run_data = run_resp.json()
        assert "run_id" in run_data
        assert run_data["procedure_id"] == pid

    @pytest.mark.asyncio
    async def test_create_run_procedure_not_found(self, client):
        run_body = {
            "procedure_id": "nonexistent_proc",
            "procedure_version": "1.0.0",
            "input_vars": {},
        }
        resp = await client.post("/api/runs", json=run_body)
        assert resp.status_code == 404


class TestGraphAPI:
    @pytest.mark.asyncio
    async def test_get_graph(self, client):
        pid = f"graph_test_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "decide",
                        "steps": [{"step_id": "s1", "action": "log", "message": "go"}],
                    },
                    "decide": {
                        "type": "logic",
                        "rules": [{"condition": "x > 0", "next_node": "end"}],
                        "default_next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        await client.post("/api/procedures", json={"ckp_json": ckp})
        resp = await client.get(f"/api/procedures/{pid}/1.0.0/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert "nodes" in data
        assert "edges" in data
        assert len(data["nodes"]) == 3
        assert len(data["edges"]) > 0

    @pytest.mark.asyncio
    async def test_get_graph_not_found(self, client):
        resp = await client.get("/api/procedures/nonexistent/1.0.0/graph")
        assert resp.status_code == 404
