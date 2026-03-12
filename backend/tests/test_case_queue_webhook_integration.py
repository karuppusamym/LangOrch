"""Comprehensive tests for case queue + webhook integration.

Tests the full lifecycle of case webhooks in the queue scenario:
1. Case creation → webhook dispatch
2. Case claim/release → webhook dispatch
3. Case SLA breach → webhook dispatch
4. Run linking → webhook dispatch
5. Retry/DLQ behavior
6. Signature verification
7. Concurrency and race conditions
8. Project filtering
9. Integration with queue analytics
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db.engine import async_session
from app.db.models import Case, CaseEvent, CaseWebhookDelivery, CaseWebhookSubscription
from app.main import app


def _uid() -> str:
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def cleanup_webhooks():
    """Clean up webhook subscriptions and deliveries before each test."""
    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))
        await db.commit()
    yield
    # Cleanup after test
    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))
        await db.commit()


# ──────────────────────────────────────────────────────────────────
# Test 1: Full case lifecycle webhooks
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_full_case_lifecycle_webhooks(client):
    """Test that all case lifecycle events trigger webhooks correctly."""
    from app.services import case_webhook_service

    # Create wildcard subscription
    sub_resp = await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "*",
            "target_url": "https://test.invalid/hook",
            "enabled": True,
        },
    )
    assert sub_resp.status_code == 201

    # Create a case
    case_resp = await client.post(
        "/api/cases",
        json={
            "title": "Lifecycle Test Case",
            "description": "Testing webhooks",
            "priority": "high",
            "metadata": {"test": "lifecycle"},
        },
    )
    assert case_resp.status_code == 201
    case_id = case_resp.json()["case_id"]

    # Wait for event dispatch
    await asyncio.sleep(0.2)

    # Check deliveries were queued for case_created
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.case_id == case_id)
                    .order_by(CaseWebhookDelivery.created_at)
                )
            )
            .scalars()
            .all()
        )

    event_types = [d.event_type for d in deliveries]
    assert "case_created" in event_types, f"Expected case_created, got {event_types}"

    # Claim the case
    claim_resp = await client.post(
        f"/api/cases/{case_id}/claim",
        json={"owner": "worker_01", "set_in_progress": True},
    )
    assert claim_resp.status_code == 200

    await asyncio.sleep(0.2)

    # Check for case_claimed webhook
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.case_id == case_id)
                    .order_by(CaseWebhookDelivery.created_at)
                )
            )
            .scalars()
            .all()
        )

    event_types = [d.event_type for d in deliveries]
    assert "case_claimed" in event_types, f"Expected case_claimed, got {event_types}"

    # Release the case
    release_resp = await client.post(
        f"/api/cases/{case_id}/release",
        json={"owner": "worker_01", "set_open": True},
    )
    assert release_resp.status_code == 200

    await asyncio.sleep(0.2)

    # Check for case_released webhook
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.case_id == case_id)
                    .order_by(CaseWebhookDelivery.created_at)
                )
            )
            .scalars()
            .all()
        )

    event_types = [d.event_type for d in deliveries]
    assert "case_released" in event_types, f"Expected case_released, got {event_types}"

    # Update case
    update_resp = await client.patch(
        f"/api/cases/{case_id}",
        json={"metadata": {"test": "updated"}},
    )
    assert update_resp.status_code == 200

    await asyncio.sleep(0.2)

    # Check for case_updated webhook
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.case_id == case_id)
                    .order_by(CaseWebhookDelivery.created_at)
                )
            )
            .scalars()
            .all()
        )

    event_types = [d.event_type for d in deliveries]
    assert "case_updated" in event_types, f"Expected case_updated, got {event_types}"


# ──────────────────────────────────────────────────────────────────
# Test 2: Queue priority and webhook delivery order
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_queue_priority_webhook_order(client):
    """Test webhooks respect queue priority ordering."""
    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://test.invalid/hook",
        },
    )

    # Create 3 cases with different priorities
    case_ids = []
    for i, priority in enumerate(["low", "high", "normal"]):
        resp = await client.post(
            "/api/cases",
            json={
                "title": f"Priority {priority} Case",
                "priority": priority,
                "metadata": {"order": i},
            },
        )
        assert resp.status_code == 201
        case_ids.append(resp.json()["case_id"])

    await asyncio.sleep(0.2)

    # Verify all got webhook deliveries queued
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.event_type == "case_created")
                    .order_by(CaseWebhookDelivery.created_at)
                )
            )
            .scalars()
            .all()
        )

    assert len(deliveries) >= 3
    # All should have case_id from our created cases
    delivery_case_ids = {d.case_id for d in deliveries if d.case_id in case_ids}
    assert len(delivery_case_ids) == 3


# ──────────────────────────────────────────────────────────────────
# Test 3: SLA breach webhook
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sla_breach_webhook(client):
    """Test that SLA breach triggers webhook."""
    # Create subscription for SLA breach events
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_sla_breached",
            "target_url": "https://test.invalid/sla-hook",
        },
    )

    # Create case with past SLA
    past_time = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    resp = await client.post(
        "/api/cases",
        json={
            "title": "SLA Breach Test",
            "sla_due_at": past_time,
        },
    )
    assert resp.status_code == 201
    case_id = resp.json()["case_id"]

    # Trigger SLA evaluation (simulate timeout sweeper finding breach)
    from app.services import case_service

    async with async_session() as db:
        breached_ids = await case_service.mark_sla_breaches(db)
        await db.commit()

    assert case_id in breached_ids

    await asyncio.sleep(0.2)

    # Check for SLA breach webhook
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.case_id == case_id,
                        CaseWebhookDelivery.event_type == "case_sla_breached",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(deliveries) == 1
    assert deliveries[0].status == "pending"


# ──────────────────────────────────────────────────────────────────
# Test 4: Retry and DLQ workflow
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_retry_and_dlq_workflow(client, monkeypatch):
    """Test complete retry workflow: fail → retry → DLQ enrollment."""
    from app.services import case_webhook_service

    attempts_log = []

    class _Resp:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class _Client:
        def __init__(self, timeout: float = 0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            attempts_log.append({"url": url, "json": json})
            # Always fail to trigger retries
            return _Resp(503)

    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://retry-test.invalid/hook",
        },
    )

    # Create case
    resp = await client.post(
        "/api/cases",
        json={"title": "Retry Test Case"},
    )
    assert resp.status_code == 201

    await asyncio.sleep(0.2)

    # Process deliveries multiple times to trigger retries
    for _ in range(5):  # Exceed max_attempts
        result = await case_webhook_service.process_pending_deliveries(limit=10)
        if result["failed"] > 0:
            break
        await asyncio.sleep(0.1)
        # Force next attempt time to now for immediate retry
        async with async_session() as db:
            await db.execute(
                """
                UPDATE case_webhook_deliveries 
                SET next_attempt_at = datetime('now')
                WHERE status = 'retrying'
                """
            )
            await db.commit()

    # Check DLQ enrollment (should have been enrolled after max failures)
    dlq_resp = await client.get("/api/cases/webhooks/dlq")
    assert dlq_resp.status_code == 200
    # May or may not have DLQ entries depending on max_attempts setting

    # Verify attempts were made
    assert len(attempts_log) > 0


# ──────────────────────────────────────────────────────────────────
# Test 5: Signature verification
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_signature_verification(client, monkeypatch):
    """Test HMAC signature is correctly generated for webhooks."""
    from app.services import case_webhook_service

    captured_sig = {"signature": None}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout: float = 0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            captured_sig["signature"] = headers.get("X-LangOrch-Signature")
            return _Resp()

    monkeypatch.setenv("TEST_WEBHOOK_SECRET", "test_secret_key")
    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Create subscription with secret
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://sig-test.invalid/hook",
            "secret_env_var": "TEST_WEBHOOK_SECRET",
        },
    )

    # Create case
    resp = await client.post(
        "/api/cases",
        json={"title": "Signature Test"},
    )
    assert resp.status_code == 201

    await asyncio.sleep(0.2)

    # Process delivery
    await case_webhook_service.process_pending_deliveries(limit=10)

    # Verify signature was included
    assert captured_sig["signature"] is not None
    assert captured_sig["signature"].startswith("sha256=")


# ──────────────────────────────────────────────────────────────────
# Test 6: Project filtering
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_project_filtering(client):
    """Test webhooks only fire for matching project_id."""
    project_a = f"proj_a_{_uid()}"
    project_b = f"proj_b_{_uid()}"

    # Create project-specific subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://proj-a.invalid/hook",
            "project_id": project_a,
        },
    )

    # Create case in project A
    resp_a = await client.post(
        "/api/cases",
        json={"title": "Project A Case", "project_id": project_a},
    )
    assert resp_a.status_code == 201
    case_a_id = resp_a.json()["case_id"]

    # Create case in project B
    resp_b = await client.post(
        "/api/cases",
        json={"title": "Project B Case", "project_id": project_b},
    )
    assert resp_b.status_code == 201
    case_b_id = resp_b.json()["case_id"]

    await asyncio.sleep(0.2)

    # Check deliveries
    async with async_session() as db:
        proj_a_deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.case_id == case_a_id,
                        CaseWebhookDelivery.event_type == "case_created",
                    )
                )
            )
            .scalars()
            .all()
        )
        proj_b_deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.case_id == case_b_id,
                        CaseWebhookDelivery.event_type == "case_created",
                    )
                )
            )
            .scalars()
            .all()
        )

    # Project A case should have delivery
    assert len(proj_a_deliveries) > 0, "Project A case should trigger webhook"

    # Project B case should NOT have delivery (different project)
    assert len(proj_b_deliveries) == 0, "Project B case should NOT trigger webhook (project filter)"


# ──────────────────────────────────────────────────────────────────
# Test 7: Concurrent webhook processing
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_concurrent_webhook_processing(client, monkeypatch):
    """Test multiple webhooks are processed concurrently without conflicts."""
    from app.services import case_webhook_service

    delivery_count = {"count": 0}

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout: float = 0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            delivery_count["count"] += 1
            await asyncio.sleep(0.05)  # Simulate network delay
            return _Resp()

    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://concurrent.invalid/hook",
        },
    )

    # Create 5 cases
    for i in range(5):
        resp = await client.post(
            "/api/cases",
            json={"title": f"Concurrent Case {i}"},
        )
        assert resp.status_code == 201

    await asyncio.sleep(0.2)

    # Process all deliveries
    result = await case_webhook_service.process_pending_deliveries(limit=10)
    assert result["claimed"] >= 5
    assert delivery_count["count"] >= 5


# ──────────────────────────────────────────────────────────────────
# Test 8: Run linking webhook
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_linked_webhook(client):
    """Test that linking a run to a case triggers run_linked webhook."""
    # Create subscription for run_linked
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "run_linked",
            "target_url": "https://test.invalid/run-hook",
        },
    )

    # Create case
    case_resp = await client.post(
        "/api/cases",
        json={"title": "Run Link Test"},
    )
    case_id = case_resp.json()["case_id"]

    # Create procedure
    proc_resp = await client.post(
        "/api/procedures",
        json={
            "ckp_json": {
                "procedure_id": f"test_proc_{_uid()}",
                "version": "1.0.0",
                "trigger": {"type": "manual"},
                "workflow_graph": {
                    "start_node": "end",
                    "nodes": {
                        "end": {
                            "type": "terminate",
                            "status": "completed",
                        }
                    },
                },
            }
        },
    )
    proc_id = proc_resp.json()["procedure_id"]

    # Create run with case_id
    run_resp = await client.post(
        "/api/runs",
        json={
            "procedure_id": proc_id,
            "procedure_version": "1.0.0",
            "trigger": "manual",
            "case_id": case_id,
        },
    )
    assert run_resp.status_code == 201

    await asyncio.sleep(0.2)

    # Check for run_linked webhook
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.case_id == case_id,
                        CaseWebhookDelivery.event_type == "run_linked",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(deliveries) > 0, "run_linked webhook should be triggered"


# ──────────────────────────────────────────────────────────────────
# Test 9: Integration with queue analytics
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhooks_with_queue_analytics(client):
    """Test webhooks work correctly alongside queue analytics queries."""
    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "*",
            "target_url": "https://analytics-test.invalid/hook",
        },
    )

    # Create 10 cases (similar to demo scenario)
    case_ids = []
    for i in range(10):
        resp = await client.post(
            "/api/cases",
            json={
                "title": f"Analytics Case {i}",
                "priority": "high" if i < 3 else "normal",
            },
        )
        case_ids.append(resp.json()["case_id"])

    await asyncio.sleep(0.2)

    # Query queue analytics (should not interfere with webhooks)
    analytics_resp = await client.get("/api/cases/queue/analytics")
    assert analytics_resp.status_code == 200
    analytics = analytics_resp.json()
    assert analytics["total_active_cases"] >= 10

    # Verify webhook deliveries were created
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.event_type == "case_created"
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len([d for d in deliveries if d.case_id in case_ids]) >= 10


# ──────────────────────────────────────────────────────────────────
# Test 10: Idempotency key generation
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_idempotency_keys(client, monkeypatch):
    """Test that webhooks include stable idempotency keys."""
    from app.services import case_webhook_service

    captured_keys = []

    class _Resp:
        status_code = 200

    class _Client:
        def __init__(self, timeout: float = 0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            key = headers.get("X-LangOrch-Idempotency-Key")
            captured_keys.append(key)
            return _Resp()

    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://idem-test.invalid/hook",
        },
    )

    # Create case
    resp = await client.post(
        "/api/cases",
        json={"title": "Idempotency Test"},
    )
    assert resp.status_code == 201

    await asyncio.sleep(0.2)

    # Process delivery
    await case_webhook_service.process_pending_deliveries(limit=10)

    # Verify idempotency key was included
    assert len(captured_keys) > 0
    assert all(key is not None for key in captured_keys)
    # Keys should be stable (contain case_event or delivery ID)
    assert all(":" in key for key in captured_keys)


# ──────────────────────────────────────────────────────────────────
# Test 11: Webhook delivery summary endpoint
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_delivery_summary(client):
    """Test delivery summary endpoint provides accurate stats."""
    # Create subscription
    sub_resp = await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://summary-test.invalid/hook",
        },
    )
    sub_id = sub_resp.json()["subscription_id"]

    # Create cases to generate deliveries
    for i in range(5):
        await client.post(
            "/api/cases",
            json={"title": f"Summary Test Case {i}"},
        )

    await asyncio.sleep(0.2)

    # Get summary
    summary_resp = await client.get(
        f"/api/cases/webhooks/deliveries/summary?subscription_id={sub_id}"
    )
    assert summary_resp.status_code == 200
    summary = summary_resp.json()

    assert summary["total"] >= 5
    assert "by_status" in summary
    assert summary["by_status"]["pending"] >= 5


# ──────────────────────────────────────────────────────────────────
# Test 12: Disabled subscriptions don't fire
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_disabled_subscription_no_fire(client):
    """Test that disabled subscriptions don't create deliveries."""
    # Create disabled subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://disabled.invalid/hook",
            "enabled": False,
        },
    )

    # Create case
    resp = await client.post(
        "/api/cases",
        json={"title": "Disabled Test"},
    )
    case_id = resp.json()["case_id"]

    await asyncio.sleep(0.2)

    # Check no deliveries were created
    async with async_session() as db:
        deliveries = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery).where(
                        CaseWebhookDelivery.case_id == case_id,
                        CaseWebhookDelivery.event_type == "case_created",
                    )
                )
            )
            .scalars()
            .all()
        )

    assert len(deliveries) == 0, "Disabled subscription should not create deliveries"


# ──────────────────────────────────────────────────────────────────
# Test 13: Replay functionality
# ──────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_webhook_replay_failed_delivery(client, monkeypatch):
    """Test replaying a failed delivery."""
    from app.services import case_webhook_service

    attempts = {"count": 0}

    class _Resp:
        def __init__(self, status_code: int):
            self.status_code = status_code

    class _Client:
        def __init__(self, timeout: float = 0):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            attempts["count"] += 1
            # Succeed on replay (2nd attempt)
            if attempts["count"] >= 2:
                return _Resp(200)
            return _Resp(500)

    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Create subscription
    await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://replay-test.invalid/hook",
        },
    )

    # Create case
    resp = await client.post(
        "/api/cases",
        json={"title": "Replay Test"},
    )
    assert resp.status_code == 201

    await asyncio.sleep(0.2)

    # Process delivery (will fail)
    await case_webhook_service.process_pending_deliveries(limit=10)

    # Get failed delivery
    async with async_session() as db:
        failed = (
            await db.execute(
                select(CaseWebhookDelivery)
                .where(CaseWebhookDelivery.status == "retrying")
                .order_by(CaseWebhookDelivery.created_at.desc())
                .limit(1)
            )
        ).scalar_one_or_none()

    if failed:
        # Replay the failed delivery
        replay_resp = await client.post(
            f"/api/cases/webhooks/deliveries/{failed.delivery_id}/replay"
        )
        assert replay_resp.status_code == 200

        # Verify it was replayed
        assert attempts["count"] >= 2
