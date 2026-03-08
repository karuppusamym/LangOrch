"""Tests for case SLA policy profiles."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _minutes_until(ts: str) -> float:
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt - datetime.now(timezone.utc)).total_seconds() / 60.0


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_sla_policy_crud_and_auto_assignment(client):
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"SLA Proj {_uid()}", "description": "sla policy test"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    create_policy = await client.post(
        "/api/cases/sla-policies",
        json={
            "name": "Incident High 30m",
            "project_id": project_id,
            "case_type": "incident",
            "priority": "high",
            "due_minutes": 30,
            "breach_status": "escalated",
            "enabled": True,
        },
    )
    assert create_policy.status_code == 201
    policy = create_policy.json()
    policy_id = policy["policy_id"]
    assert policy["due_minutes"] == 30

    case_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Incident {_uid()}",
            "project_id": project_id,
            "case_type": "incident",
            "priority": "high",
        },
    )
    assert case_resp.status_code == 201
    case_data = case_resp.json()
    assert case_data["sla_due_at"] is not None
    mins = _minutes_until(case_data["sla_due_at"])
    assert 25 <= mins <= 35, f"expected ~30m SLA, got {mins:.2f}"

    patch_policy = await client.patch(
        f"/api/cases/sla-policies/{policy_id}",
        json={"due_minutes": 45},
    )
    assert patch_policy.status_code == 200
    assert patch_policy.json()["due_minutes"] == 45

    case_resp_2 = await client.post(
        "/api/cases",
        json={
            "title": f"Incident 2 {_uid()}",
            "project_id": project_id,
            "case_type": "incident",
            "priority": "high",
        },
    )
    assert case_resp_2.status_code == 201
    mins2 = _minutes_until(case_resp_2.json()["sla_due_at"])
    assert 40 <= mins2 <= 50, f"expected ~45m SLA, got {mins2:.2f}"

    list_resp = await client.get(f"/api/cases/sla-policies?project_id={project_id}")
    assert list_resp.status_code == 200
    ids = {p["policy_id"] for p in list_resp.json()}
    assert policy_id in ids

    del_resp = await client.delete(f"/api/cases/sla-policies/{policy_id}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_sla_policy_precedence_specific_then_project_then_global(client):
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"Precedence {_uid()}", "description": "precedence test"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    # Global default for high priority
    r = await client.post(
        "/api/cases/sla-policies",
        json={"name": "Global High", "priority": "high", "due_minutes": 120},
    )
    assert r.status_code == 201

    # Project-specific fallback for high priority
    r = await client.post(
        "/api/cases/sla-policies",
        json={
            "name": "Project High",
            "project_id": project_id,
            "priority": "high",
            "due_minutes": 15,
        },
    )
    assert r.status_code == 201

    # Most specific: project + case_type + priority
    r = await client.post(
        "/api/cases/sla-policies",
        json={
            "name": "Project Incident High",
            "project_id": project_id,
            "case_type": "incident",
            "priority": "high",
            "due_minutes": 5,
        },
    )
    assert r.status_code == 201

    specific_case = await client.post(
        "/api/cases",
        json={
            "title": f"Specific {_uid()}",
            "project_id": project_id,
            "case_type": "incident",
            "priority": "high",
        },
    )
    assert specific_case.status_code == 201
    mins_specific = _minutes_until(specific_case.json()["sla_due_at"])
    assert 2 <= mins_specific <= 8, f"expected ~5m SLA, got {mins_specific:.2f}"

    project_case = await client.post(
        "/api/cases",
        json={
            "title": f"Project {_uid()}",
            "project_id": project_id,
            "priority": "high",
        },
    )
    assert project_case.status_code == 201
    mins_project = _minutes_until(project_case.json()["sla_due_at"])
    assert 10 <= mins_project <= 20, f"expected ~15m SLA, got {mins_project:.2f}"

    global_case = await client.post(
        "/api/cases",
        json={
            "title": f"Global {_uid()}",
            "priority": "high",
        },
    )
    assert global_case.status_code == 201
    mins_global = _minutes_until(global_case.json()["sla_due_at"])
    assert 110 <= mins_global <= 130, f"expected ~120m SLA, got {mins_global:.2f}"
