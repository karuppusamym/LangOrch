"""Case-centric API tests."""

from __future__ import annotations

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


@pytest.mark.asyncio
async def test_case_crud_and_events(client):
    proj_resp = await client.post(
        "/api/projects",
        json={"name": f"Case Project {_uid()}", "description": "project for case tests"},
    )
    assert proj_resp.status_code == 201
    project_id = proj_resp.json()["project_id"]

    create_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Customer Incident {_uid()}",
            "project_id": project_id,
            "external_ref": "INC-1001",
            "status": "open",
            "priority": "high",
            "owner": "ops-team",
            "tags": ["incident", "vip"],
            "metadata": {"source": "api-test"},
        },
    )
    assert create_resp.status_code == 201
    case = create_resp.json()
    case_id = case["case_id"]
    assert case["project_id"] == project_id
    assert case["external_ref"] == "INC-1001"
    assert case["tags"] == ["incident", "vip"]

    get_resp = await client.get(f"/api/cases/{case_id}")
    assert get_resp.status_code == 200
    assert get_resp.json()["case_id"] == case_id

    patch_resp = await client.patch(
        f"/api/cases/{case_id}",
        json={"status": "in_progress", "owner": "analyst-1"},
    )
    assert patch_resp.status_code == 200
    patched = patch_resp.json()
    assert patched["status"] == "in_progress"
    assert patched["owner"] == "analyst-1"

    list_resp = await client.get(f"/api/cases?project_id={project_id}&status=in_progress")
    assert list_resp.status_code == 200
    listed_ids = {item["case_id"] for item in list_resp.json()}
    assert case_id in listed_ids

    events_resp = await client.get(f"/api/cases/{case_id}/events")
    assert events_resp.status_code == 200
    event_types = [ev["event_type"] for ev in events_resp.json()]
    assert "case_created" in event_types
    assert "case_updated" in event_types

    del_resp = await client.delete(f"/api/cases/{case_id}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_case_linked_run_blocks_delete(client):
    pid = f"case_run_proc_{_uid()}"
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
                    "steps": [{"step_id": "s1", "action": "log", "message": "x"}],
                },
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }
    import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
    assert import_resp.status_code == 201

    case_resp = await client.post(
        "/api/cases",
        json={"title": f"Case {_uid()}", "status": "open"},
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": pid,
            "procedure_version": "1.0.0",
            "input_vars": {},
            "case_id": case_id,
        },
    )
    assert run_resp.status_code == 201
    run = run_resp.json()
    assert run["case_id"] == case_id

    del_resp = await client.delete(f"/api/cases/{case_id}")
    assert del_resp.status_code == 409
    assert "linked runs" in del_resp.json()["detail"]

    events_resp = await client.get(f"/api/cases/{case_id}/events")
    assert events_resp.status_code == 200
    event_types = [ev["event_type"] for ev in events_resp.json()]
    assert "run_linked" in event_types


@pytest.mark.asyncio
async def test_case_queue_claim_release_and_sla_breach(client):
    now = datetime.now(timezone.utc)
    overdue_due = (now - timedelta(hours=1)).isoformat()
    future_due = (now + timedelta(hours=2)).isoformat()

    overdue_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Overdue {_uid()}",
            "priority": "low",
            "sla_due_at": overdue_due,
        },
    )
    assert overdue_resp.status_code == 201
    overdue_case = overdue_resp.json()

    high_resp = await client.post(
        "/api/cases",
        json={
            "title": f"High {_uid()}",
            "priority": "high",
            "sla_due_at": future_due,
        },
    )
    assert high_resp.status_code == 201
    high_case = high_resp.json()

    queue_resp = await client.get("/api/cases/queue")
    assert queue_resp.status_code == 200
    queue = queue_resp.json()
    queue_ids = [row["case_id"] for row in queue]
    assert queue_ids.index(overdue_case["case_id"]) < queue_ids.index(high_case["case_id"])

    overdue_entry = next(row for row in queue if row["case_id"] == overdue_case["case_id"])
    assert overdue_entry["is_sla_breached"] is True

    claim_resp = await client.post(
        f"/api/cases/{overdue_case['case_id']}/claim",
        json={"owner": "ops-a", "set_in_progress": True},
    )
    assert claim_resp.status_code == 200
    claimed = claim_resp.json()
    assert claimed["owner"] == "ops-a"
    assert claimed["status"] == "in_progress"

    claim_conflict = await client.post(
        f"/api/cases/{overdue_case['case_id']}/claim",
        json={"owner": "ops-b", "set_in_progress": True},
    )
    assert claim_conflict.status_code == 409

    release_conflict = await client.post(
        f"/api/cases/{overdue_case['case_id']}/release",
        json={"owner": "ops-b", "set_open": False},
    )
    assert release_conflict.status_code == 409

    release_ok = await client.post(
        f"/api/cases/{overdue_case['case_id']}/release",
        json={"owner": "ops-a", "set_open": True},
    )
    assert release_ok.status_code == 200
    released = release_ok.json()
    assert released["owner"] is None
    assert released["status"] == "open"

    # Service-level SLA mark should set escalated + breach timestamp.
    from app.db.engine import async_session
    from app.services import case_service

    async with async_session() as db:
        breached = await case_service.mark_sla_breaches(db)
        await db.commit()
    assert overdue_case["case_id"] in breached

    refreshed = await client.get(f"/api/cases/{overdue_case['case_id']}")
    assert refreshed.status_code == 200
    refreshed_case = refreshed.json()
    assert refreshed_case["status"] == "escalated"
    assert refreshed_case["sla_breached_at"] is not None

    events_resp = await client.get(f"/api/cases/{overdue_case['case_id']}/events")
    assert events_resp.status_code == 200
    event_types = [ev["event_type"] for ev in events_resp.json()]
    assert "case_claimed" in event_types
    assert "case_released" in event_types
    assert "case_sla_breached" in event_types


@pytest.mark.asyncio
async def test_case_queue_analytics_endpoint(client):
    now = datetime.now(timezone.utc)
    overdue_due = (now - timedelta(hours=1)).isoformat()
    soon_due = (now + timedelta(minutes=30)).isoformat()
    later_due = (now + timedelta(hours=4)).isoformat()

    overdue_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Analytics Overdue {_uid()}",
            "priority": "high",
            "sla_due_at": overdue_due,
        },
    )
    assert overdue_resp.status_code == 201

    soon_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Analytics Soon {_uid()}",
            "priority": "normal",
            "sla_due_at": soon_due,
        },
    )
    assert soon_resp.status_code == 201

    later_resp = await client.post(
        "/api/cases",
        json={
            "title": f"Analytics Later {_uid()}",
            "priority": "low",
            "owner": "ops-a",
            "sla_due_at": later_due,
        },
    )
    assert later_resp.status_code == 201

    analytics_resp = await client.get("/api/cases/queue/analytics?risk_window_minutes=60")
    assert analytics_resp.status_code == 200
    analytics = analytics_resp.json()

    assert analytics["total_active_cases"] >= 3
    assert analytics["breached_cases"] >= 1
    assert analytics["breach_risk_next_window_cases"] >= 1
    assert 0 <= analytics["breach_risk_next_window_percent"] <= 100
    assert analytics["wait_p50_seconds"] >= 0
    assert analytics["wait_p95_seconds"] >= analytics["wait_p50_seconds"]
    assert 0 <= analytics["reassignment_rate_24h"] <= 100
    assert 0 <= analytics["abandonment_rate_24h"] <= 100
    assert "high" in analytics["wait_by_priority"]
    assert "wait_p95_seconds" in analytics["wait_by_priority"]["high"]
    assert "unknown" in analytics["wait_by_case_type"]
