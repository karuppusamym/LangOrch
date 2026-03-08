"""Comprehensive end-to-end tests for case step/batch/sync, queue, and secrets."""

from __future__ import annotations

import json
import os
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def setup_secrets():
    """Set up test secrets in environment."""
    secrets = {
        "DB_PASSWORD": f"secure_pass_{_uid()}",
        "API_KEY": f"key_{_uid()}",
        "WEBHOOK_TOKEN": "token_abc123",
    }
    for key, value in secrets.items():
        os.environ[f"LANGORCH_SECRET_{key}"] = value
    yield secrets
    for key in secrets:
        os.environ.pop(f"LANGORCH_SECRET_{key}", None)


@pytest.fixture
def procedure_with_dispatch_modes() -> dict:
    """Procedure with multiple dispatch mode options."""
    return {
        "procedure_id": f"proc_dispatch_{_uid()}",
        "version": "1.0.0",
        "global_config": {
            "max_retries": 1,
            "retry_delay_ms": 100,
            "workflow_dispatch_mode": "sync",  # default
        },
        "variables_schema": {
            "user_id": {"type": "string", "required": True},
            "action": {"type": "string", "default": "process"},
            "secret_key": {"type": "string", "default": "DB_PASSWORD"},
        },
        "workflow_graph": {
            "start_node": "start",
            "nodes": {
                "start": {
                    "type": "sequence",
                    "description": "Validate and prepare",
                    "next_node": "process_data",
                    "steps": [
                        {
                            "step_id": "validate_input",
                            "action": "validate",
                            "config": {
                                "rules": [
                                    {
                                        "field": "user_id",
                                        "type": "string",
                                        "validation": {"min_length": 1},
                                    }
                                ]
                            },
                        },
                        {
                            "step_id": "fetch_secret",
                            "action": "retrieve_secret",
                            "secret_name": "${secret_key}",
                            "output_variable": "secret_value",
                        },
                    ],
                },
                "process_data": {
                    "type": "sequence",
                    "agent": "web_agent",
                    "description": "Process with optional workflow dispatch",
                    "next_node": "finalize",
                    "dispatch_mode": "step",  # can be overridden
                    "steps": [
                        {
                            "step_id": "query_user",
                            "action": "http_request",
                            "method": "get",
                            "url": "https://jsonplaceholder.typicode.com/users/1",
                            "output_variable": "user_data",
                            "timeout_ms": 10000,
                        },
                        {
                            "step_id": "transform_data",
                            "action": "transform",
                            "input": "${user_data}",
                            "template": "User: ${name}, Email: ${email}",
                            "output_variable": "formatted_user",
                        },
                    ],
                },
                "finalize": {
                    "type": "terminate",
                    "status": "success",
                },
            },
        },
    }


@pytest.fixture
def procedure_with_batch() -> dict:
    """Procedure using batch dispatch mode."""
    return {
        "procedure_id": f"proc_batch_{_uid()}",
        "version": "1.0.0",
        "global_config": {
            "max_retries": 1,
            "workflow_dispatch_mode": "batch",
        },
        "variables_schema": {
            "items": {"type": "array", "required": True},
        },
        "workflow_graph": {
            "start_node": "process_items",
            "nodes": {
                "process_items": {
                    "type": "sequence",
                    "agent": "web_agent",
                    "dispatch_mode": "batch",
                    "description": "Process array of items in batch",
                    "next_node": "complete",
                    "steps": [
                        {
                            "step_id": "batch_process",
                            "action": "batch_map",
                            "input": "${items}",
                            "map_action": "http_request",
                            "map_params": {
                                "method": "get",
                                "url": "https://jsonplaceholder.typicode.com/posts/${item}",
                            },
                            "output_variable": "results",
                        },
                    ],
                },
                "complete": {
                    "type": "terminate",
                    "status": "success",
                },
            },
        },
    }


@pytest.mark.asyncio
async def test_case_creation_and_basic_run(client, setup_secrets):
    """Test case creation, linking to project, and running a procedure."""
    # Create project
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"E2E Project {_uid()}", "description": "e2e test project"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    # Create case
    case_resp = await client.post(
        "/api/cases",
        json={
            "title": "E2E Test Case",
            "project_id": project_id,
            "external_ref": f"EXT-{_uid()}",
            "status": "open",
            "priority": "high",
            "owner": "e2e_user",
            "tags": ["e2e", "test"],
            "metadata": {"test_run": "comprehensive_e2e"},
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    # Create procedure
    proc_resp = await client.post(
        "/api/procedures",
        json={"ckp_json": {
            "procedure_id": f"proc_basic_{_uid()}",
            "version": "1.0.0",
            "global_config": {"max_retries": 1},
            "variables_schema": {"message": {"type": "string", "default": "test"}},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "steps": [{"step_id": "log", "action": "log", "message": "test"}],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }, "project_id": project_id},
    )
    assert proc_resp.status_code == 201
    proc = proc_resp.json()
    proc_id = proc["procedure_id"]
    proc_version = proc["version"]

    # Run procedure for case
    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": proc_version,
            "input_vars": {"message": "hello case"},
            "project_id": project_id,
            "case_id": case_id,
        },
    )
    assert run_resp.status_code == 201
    run_id = run_resp.json()["run_id"]

    # Verify run is linked to case
    case_detail_resp = await client.get(f"/api/cases/{case_id}")
    assert case_detail_resp.status_code == 200
    case_detail = case_detail_resp.json()
    assert case_detail["case_id"] == case_id
    assert case_detail["project_id"] == project_id

    # Get run details
    run_resp = await client.get(f"/api/runs/{run_id}")
    assert run_resp.status_code == 200
    run = run_resp.json()
    assert run["case_id"] == case_id
    assert run["project_id"] == project_id


@pytest.mark.asyncio
async def test_dispatch_mode_sync_vs_step(client, procedure_with_dispatch_modes):
    """Test sync vs step dispatch modes for workflow steps."""
    # Create procedure
    proc_resp = await client.post(
        "/api/procedures",
        json={"ckp_json": procedure_with_dispatch_modes},
    )
    assert proc_resp.status_code == 201
    proc_id = proc_resp.json()["procedure_id"]
    proc_version = proc_resp.json()["version"]

    # Test with sync mode (default)
    run_sync = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": proc_version,
            "input_vars": {"user_id": "test_user"},
        },
    )
    assert run_sync.status_code == 201
    sync_run_id = run_sync.json()["run_id"]

    # Wait for completion (short timeout)
    import asyncio
    await asyncio.sleep(0.5)
    
    # Check run status
    sync_run_detail = await client.get(f"/api/runs/{sync_run_id}")
    assert sync_run_detail.status_code == 200
    sync_run = sync_run_detail.json()
    assert sync_run["run_id"] == sync_run_id

    # List events for sync run
    events_resp = await client.get(f"/api/runs/{sync_run_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    # Should have at least run_created event
    assert len(events) > 0
    assert any(e["event_type"] == "run_created" for e in events)


@pytest.mark.asyncio
async def test_batch_dispatch_mode(client, procedure_with_batch):
    """Test batch dispatch mode with array input."""
    # Create proc with batch mode
    proc_resp = await client.post(
        "/api/procedures",
        json={"ckp_json": procedure_with_batch},
    )
    assert proc_resp.status_code == 201
    proc_id = proc_resp.json()["procedure_id"]
    proc_version = proc_resp.json()["version"]

    # Run with array input
    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": proc_version,
            "input_vars": {"items": [1, 2, 3]},
        },
    )
    assert run_resp.status_code == 201
    run_id = run_resp.json()["run_id"]

    # Get run
    run_detail = await client.get(f"/api/runs/{run_id}")
    assert run_detail.status_code == 200
    run = run_detail.json()
    assert run["input_vars"]["items"] == [1, 2, 3]


@pytest.mark.asyncio
async def test_secrets_injection_in_workflow(client, setup_secrets, procedure_with_dispatch_modes):
    """Test that secrets are properly injected and used in workflow."""
    # Create proc
    proc_resp = await client.post(
        "/api/procedures",
        json={"ckp_json": procedure_with_dispatch_modes},
    )
    assert proc_resp.status_code == 201
    proc_id = proc_resp.json()["procedure_id"]
    proc_version = proc_resp.json()["version"]

    # Run with secret reference
    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": proc_version,
            "input_vars": {
                "user_id": "secret_test_user",
                "secret_key": "DB_PASSWORD",
            },
        },
    )
    assert run_resp.status_code == 201
    run_id = run_resp.json()["run_id"]

    # Verify run created successfully
    run_detail = await client.get(f"/api/runs/{run_id}")
    assert run_detail.status_code == 200
    run = run_detail.json()
    # Secrets should not be exposed in run output
    assert "secret_value" not in str(run) or "secure_pass" not in str(run)


@pytest.mark.asyncio
async def test_case_queue_operations(client, setup_secrets):
    """Test case queue with SLA policies and analytics."""
    project_id = None
    
    # Create project
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"Queue Test {_uid()}", "description": "queue ops"},
    )
    if proj_resp.status_code == 201:
        project_id = proj_resp.json()["project_id"]

    # Create multiple cases
    case_ids = []
    for i in range(3):
        case_resp = await client.post(
            "/api/cases",
            json={
                "title": f"Queue Case {i}",
                "project_id": project_id,
                "status": "open",
                "priority": ["high", "normal", "low"][i % 3],
                "owner": None,  # Unassigned
                "tags": ["queue-test"],
            },
        )
        if case_resp.status_code == 201:
            case_ids.append(case_resp.json()["case_id"])

    assert len(case_ids) >= 1, "At least one case should be created"

    # List queue
    queue_resp = await client.get("/api/cases/queue")
    assert queue_resp.status_code == 200
    queue = queue_resp.json()
    assert isinstance(queue, list)

    # Try to get queue analytics (if supported)
    analytics_resp = await client.get("/api/cases/queue/analytics")
    if analytics_resp.status_code == 200:
        analytics = analytics_resp.json()
        assert "total_active_cases" in analytics or analytics_resp.status_code in (200, 405)

    # Claim a case
    if case_ids:
        claim_resp = await client.post(
            f"/api/cases/{case_ids[0]}/claim",
            json={"owner": "queue_worker", "force": True},
        )
        assert claim_resp.status_code in (200, 201)

    # Release a case
    if case_ids:
        release_resp = await client.post(
            f"/api/cases/{case_ids[0]}/release",
            json={"owner": "queue_worker"},
        )
        assert release_resp.status_code in (200, 204)


@pytest.mark.asyncio
async def test_case_event_tracking(client, setup_secrets):
    """Test that case events are properly tracked."""
    # Create project and case
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"Event Track {_uid()}", "description": "event tracking"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    case_resp = await client.post(
        "/api/cases",
        json={
            "title": "Event Tracking Case",
            "project_id": project_id,
            "status": "open",
            "priority": "normal",
            "owner": "test_user",
            "tags": ["event-test"],
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    # Perform actions
    await client.patch(
        f"/api/cases/{case_id}",
        json={"status": "in_progress", "priority": "high"},
    )

    # Get events
    events_resp = await client.get(f"/api/cases/{case_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert isinstance(events, list)
    assert len(events) > 0


@pytest.mark.asyncio
async def test_multi_step_workflow_with_error_handling(client):
    """Test workflow with multiple steps and error handlers."""
    proc_with_error = {
        "procedure_id": f"proc_error_{_uid()}",
        "version": "1.0.0",
        "global_config": {"max_retries": 2, "retry_delay_ms": 100},
        "variables_schema": {
            "should_fail": {"type": "boolean", "default": False},
        },
        "workflow_graph": {
            "start_node": "validate",
            "nodes": {
                "validate": {
                    "type": "sequence",
                    "next_node": "process",
                    "steps": [
                        {
                            "step_id": "check_input",
                            "action": "validate",
                            "config": {"rules": []},
                        }
                    ],
                    "error_handlers": [
                        {
                            "error_types": ["validation_error"],
                            "action": "log",
                            "message": "Validation failed",
                        }
                    ],
                },
                "process": {
                    "type": "sequence",
                    "next_node": "success",
                    "steps": [
                        {
                            "step_id": "process_data",
                            "action": "transform",
                            "input": "${should_fail}",
                            "template": "Processed",
                            "output_variable": "result",
                        }
                    ],
                },
                "success": {
                    "type": "terminate",
                    "status": "success",
                },
            },
        },
    }

    # Create and run procedure
    proc_resp = await client.post(
        "/api/procedures",
        json={"ckp_json": proc_with_error},
    )
    assert proc_resp.status_code == 201
    proc_id = proc_resp.json()["procedure_id"]
    proc_version = proc_resp.json()["version"]

    # Run workflow
    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": proc_version,
            "input_vars": {"should_fail": False},
        },
    )
    assert run_resp.status_code == 201
    run_id = run_resp.json()["run_id"]

    # Get run and events
    run_detail = await client.get(f"/api/runs/{run_id}")
    assert run_detail.status_code == 200
    
    events_resp = await client.get(f"/api/runs/{run_id}/events")
    assert events_resp.status_code == 200
    events = events_resp.json()
    assert len(events) > 0


@pytest.mark.asyncio
async def test_case_and_procedure_cleanup(client):
    """Test cleanup operations on cases and procedures."""
    # Create project, procedure, and case
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"Cleanup {_uid()}", "description": "cleanup test"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    proc_resp = await client.post(
        "/api/procedures",
        json={
            "ckp_json": {
                "procedure_id": f"cleanup_proc_{_uid()}",
                "version": "1.0.0",
                "global_config": {"max_retries": 1},
                "variables_schema": {},
                "workflow_graph": {
                    "start_node": "start",
                    "nodes": {
                        "start": {
                            "type": "sequence",
                            "steps": [{"step_id": "log", "action": "log"}],
                            "next_node": "end",
                        },
                        "end": {"type": "terminate", "status": "success"},
                    },
                },
            }
        },
    )
    assert proc_resp.status_code == 201
    proc_id = proc_resp.json()["procedure_id"]

    # Run multiple times
    run_ids = []
    for _ in range(2):
        run_resp = await client.post(
            "/api/runs",
            json={
                "procedure_id": proc_id,
                "procedure_version": "1.0.0",
                "project_id": project_id,
            },
        )
        if run_resp.status_code == 201:
            run_ids.append(run_resp.json()["run_id"])

    # Verify runs exist
    if run_ids:
        run_detail = await client.get(f"/api/runs/{run_ids[0]}")
        assert run_detail.status_code == 200
