"""Tests for case webhook subscriptions and dispatch."""

from __future__ import annotations

import uuid

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
async def test_case_webhook_subscription_crud(client):
    create_resp = await client.post(
        "/api/cases/webhooks",
        json={
            "event_type": "case_created",
            "target_url": "https://example.invalid/hook",
            "enabled": True,
        },
    )
    assert create_resp.status_code == 201
    sub = create_resp.json()
    assert sub["event_type"] == "case_created"
    sub_id = sub["subscription_id"]

    list_resp = await client.get("/api/cases/webhooks")
    assert list_resp.status_code == 200
    ids = {row["subscription_id"] for row in list_resp.json()}
    assert sub_id in ids

    del_resp = await client.delete(f"/api/cases/webhooks/{sub_id}")
    assert del_resp.status_code == 204


@pytest.mark.asyncio
async def test_dispatch_case_event_webhooks_with_filters_and_signature(monkeypatch):
    from app.db.engine import async_session
    from app.services import case_webhook_service
    from app.services.case_webhook_service import create_subscription, dispatch_case_event_webhooks

    posts: list[dict] = []

    class _Resp:
        def __init__(self, status_code: int = 200):
            self.status_code = status_code

    class _Client:
        def __init__(self, timeout: float = 0):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            posts.append({"url": url, "json": json, "headers": headers or {}})
            return _Resp(200)

    monkeypatch.setenv("CASE_WEBHOOK_SECRET", "supersecret")
    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    project_id = f"proj_{_uid()}"
    async with async_session() as db:
        await create_subscription(
            db,
            event_type="case_created",
            target_url="https://sub-1.invalid/hook",
            project_id=project_id,
            secret_env_var="CASE_WEBHOOK_SECRET",
        )
        await create_subscription(
            db,
            event_type="*",
            target_url="https://sub-all.invalid/hook",
            project_id=None,
        )
        await create_subscription(
            db,
            event_type="case_updated",
            target_url="https://sub-ignore.invalid/hook",
            project_id=project_id,
        )
        await db.commit()

    await dispatch_case_event_webhooks(
        {
            "event_type": "case_created",
            "case_id": "case_1",
            "project_id": project_id,
            "payload": {"hello": "world"},
        }
    )

    assert len(posts) == 2
    by_url = {item["url"]: item for item in posts}
    assert "https://sub-1.invalid/hook" in by_url
    assert "https://sub-all.invalid/hook" in by_url
    assert "X-LangOrch-Signature" in by_url["https://sub-1.invalid/hook"]["headers"]
    assert "X-LangOrch-Signature" not in by_url["https://sub-all.invalid/hook"]["headers"]
    assert "X-LangOrch-Idempotency-Key" in by_url["https://sub-1.invalid/hook"]["headers"]
    assert "X-LangOrch-Idempotency-Key" in by_url["https://sub-all.invalid/hook"]["headers"]


@pytest.mark.asyncio
async def test_emit_case_event_schedules_run_linked_dispatch(monkeypatch):
    from sqlalchemy import select

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery
    from app.services import case_service, case_webhook_service, run_service

    async with async_session() as db:
        await case_webhook_service.create_subscription(
            db,
            event_type="*",
            target_url="https://delivery-check.invalid/hook",
            project_id=None,
        )
        await db.commit()

    async with async_session() as db:
        case = await case_service.create_case(
            db,
            title=f"Case {_uid()}",
            project_id=None,
        )
        await run_service.create_run(
            db,
            procedure_id=f"proc_{_uid()}",
            procedure_version="1.0.0",
            input_vars={"x": 1},
            case_id=case.case_id,
        )
        await db.commit()

    async with async_session() as db:
        rows = list((await db.execute(select(CaseWebhookDelivery))).scalars().all())
    event_types = {row.event_type for row in rows}
    assert "case_created" in event_types
    assert "run_linked" in event_types


@pytest.mark.asyncio
async def test_process_pending_deliveries_retries_then_succeeds(monkeypatch):
    from sqlalchemy import delete, select

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription
    from app.services import case_webhook_service

    attempts = {"count": 0}

    class _Resp:
        def __init__(self, status_code: int = 200):
            self.status_code = status_code

    class _Client:
        def __init__(self, timeout: float = 0):
            self.timeout = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return _Resp(503)
            return _Resp(200)

    monkeypatch.setattr(case_webhook_service.httpx, "AsyncClient", _Client)

    # Isolate this test from prior webhook rows created by other tests.
    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))
        await db.commit()

    event = {
        "event_id": 123,
        "event_type": "case_created",
        "case_id": "case_retry",
        "project_id": None,
        "payload": {"k": "v"},
    }

    async with async_session() as db:
        await case_webhook_service.create_subscription(
            db,
            event_type="case_created",
            target_url="https://retry-test.invalid/hook",
        )
        await case_webhook_service.enqueue_case_event_webhooks(db, event)
        await db.commit()

    first = await case_webhook_service.process_pending_deliveries(limit=10)
    assert first["claimed"] == 1
    assert first["retried"] == 1

    # Force immediate retry in test for deterministic second processing pass.
    async with async_session() as db:
        row = (
            await db.execute(select(CaseWebhookDelivery).order_by(CaseWebhookDelivery.created_at.desc()).limit(1))
        ).scalar_one()
        row.next_attempt_at = row.created_at
        await db.commit()

    second = await case_webhook_service.process_pending_deliveries(limit=10)
    assert second["claimed"] == 1
    assert second["delivered"] == 1

    async with async_session() as db:
        final_row = (
            await db.execute(select(CaseWebhookDelivery).order_by(CaseWebhookDelivery.created_at.desc()).limit(1))
        ).scalar_one()
        assert final_row.status == "delivered"
        assert int(final_row.attempts or 0) >= 1


@pytest.mark.asyncio
async def test_case_webhook_delivery_list_and_replay_endpoints(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="case_created",
            target_url="https://ops.invalid/hook",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_event_id=1,
                case_id="case_ops_1",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                last_status_code=503,
                last_error="HTTP 503",
            )
        )
        await db.commit()

    list_resp = await client.get("/api/cases/webhooks/deliveries?status=failed")
    assert list_resp.status_code == 200
    rows = list_resp.json()
    assert len(rows) >= 1
    delivery = rows[0]
    assert delivery["status"] == "failed"

    replay_resp = await client.post(f"/api/cases/webhooks/deliveries/{delivery['delivery_id']}/replay")
    assert replay_resp.status_code == 200
    assert replay_resp.json()["replayed"] == 1

    list_retrying = await client.get(
        f"/api/cases/webhooks/deliveries?status=retrying&case_id={delivery['case_id']}"
    )
    assert list_retrying.status_code == 200
    assert any(row["delivery_id"] == delivery["delivery_id"] for row in list_retrying.json())


@pytest.mark.asyncio
async def test_case_webhook_replay_failed_bulk_endpoint(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-bulk",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        for idx in range(3):
            db.add(
                CaseWebhookDelivery(
                    subscription_id=sub.subscription_id,
                    case_event_id=200 + idx,
                    case_id="case_bulk",
                    event_type="case_updated",
                    payload_json='{"event_type":"case_updated"}',
                    status="failed",
                    attempts=5,
                    max_attempts=5,
                    next_attempt_at=now,
                    last_status_code=500,
                    last_error="HTTP 500",
                )
            )
        await db.commit()

    replay_resp = await client.post("/api/cases/webhooks/deliveries/replay-failed?case_id=case_bulk&limit=2")
    assert replay_resp.status_code == 200
    payload = replay_resp.json()
    assert payload["replayed"] == 2
    assert len(payload["delivery_ids"]) == 2

    list_retrying = await client.get("/api/cases/webhooks/deliveries?status=retrying&case_id=case_bulk")
    assert list_retrying.status_code == 200
    assert len(list_retrying.json()) == 2


@pytest.mark.asyncio
async def test_case_webhook_delivery_summary_endpoint(client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-summary",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_sum",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="delivered",
                attempts=1,
                max_attempts=5,
                next_attempt_at=now,
                delivered_at=now,
                updated_at=now,
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_sum",
                event_type="case_updated",
                payload_json='{"event_type":"case_updated"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                updated_at=now,
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_sum",
                event_type="case_updated",
                payload_json='{"event_type":"case_updated"}',
                status="retrying",
                attempts=2,
                max_attempts=5,
                next_attempt_at=now + timedelta(minutes=1),
                created_at=now - timedelta(minutes=2),
                updated_at=now,
            )
        )
        await db.commit()

    resp = await client.get("/api/cases/webhooks/deliveries/summary")
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total"] == 3
    assert summary["by_status"]["delivered"] == 1
    assert summary["by_status"]["failed"] == 1
    assert summary["by_status"]["retrying"] == 1
    assert summary["recent_failures_last_hour"] == 1
    assert summary["oldest_pending_age_seconds"] is not None
    assert summary["oldest_pending_age_seconds"] >= 60


@pytest.mark.asyncio
async def test_case_webhook_delivery_summary_filters(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub_a = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-a",
            enabled=True,
        )
        sub_b = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-b",
            enabled=True,
        )
        db.add(sub_a)
        db.add(sub_b)
        await db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub_a.subscription_id,
                case_id="case_filter_a",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                updated_at=now,
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub_b.subscription_id,
                case_id="case_filter_b",
                event_type="case_updated",
                payload_json='{"event_type":"case_updated"}',
                status="delivered",
                attempts=1,
                max_attempts=5,
                next_attempt_at=now,
                delivered_at=now,
                updated_at=now,
            )
        )
        await db.commit()

    resp = await client.get(
        f"/api/cases/webhooks/deliveries/summary?subscription_id={sub_a.subscription_id}"
    )
    assert resp.status_code == 200
    summary = resp.json()
    assert summary["total"] == 1
    assert summary["by_status"]["failed"] == 1
    assert summary["recent_failures_last_hour"] == 1


@pytest.mark.asyncio
async def test_case_webhook_dlq_endpoints(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_event_id=901,
                case_id="case_dlq",
                event_type="case_updated",
                payload_json='{"event_type":"case_updated"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                last_status_code=500,
                last_error="HTTP 500",
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_event_id=902,
                case_id="case_dlq",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="delivered",
                attempts=1,
                max_attempts=5,
                next_attempt_at=now,
                delivered_at=now,
            )
        )
        await db.commit()

    dlq_list = await client.get("/api/cases/webhooks/dlq?case_id=case_dlq")
    assert dlq_list.status_code == 200
    rows = dlq_list.json()
    assert len(rows) == 1
    assert rows[0]["status"] == "failed"

    dlq_replay = await client.post("/api/cases/webhooks/dlq/replay?case_id=case_dlq")
    assert dlq_replay.status_code == 200
    payload = dlq_replay.json()
    assert payload["replayed"] == 1
    assert len(payload["delivery_ids"]) == 1

    dlq_after = await client.get("/api/cases/webhooks/dlq?case_id=case_dlq")
    assert dlq_after.status_code == 200
    assert dlq_after.json() == []


@pytest.mark.asyncio
async def test_case_webhook_dlq_sorting_and_order(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq-sort",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        for attempts in (3, 1, 5):
            db.add(
                CaseWebhookDelivery(
                    subscription_id=sub.subscription_id,
                    case_id="case_dlq_sort",
                    event_type="case_updated",
                    payload_json='{"event_type":"case_updated"}',
                    status="failed",
                    attempts=attempts,
                    max_attempts=5,
                    next_attempt_at=now,
                    last_status_code=500,
                    last_error="HTTP 500",
                )
            )
        await db.commit()

    asc_resp = await client.get(
        "/api/cases/webhooks/dlq?case_id=case_dlq_sort&sort_by=attempts&order=asc"
    )
    assert asc_resp.status_code == 200
    asc_attempts = [row["attempts"] for row in asc_resp.json()]
    assert asc_attempts == [1, 3, 5]

    desc_resp = await client.get(
        "/api/cases/webhooks/dlq?case_id=case_dlq_sort&sort_by=attempts&order=desc"
    )
    assert desc_resp.status_code == 200
    desc_attempts = [row["attempts"] for row in desc_resp.json()]
    assert desc_attempts == [5, 3, 1]


@pytest.mark.asyncio
async def test_case_webhook_dlq_replay_selected_endpoint(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq-selected",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        d1 = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_selected",
            event_type="case_updated",
            payload_json='{"event_type":"case_updated"}',
            status="failed",
            attempts=5,
            max_attempts=5,
            next_attempt_at=now,
            last_status_code=500,
            last_error="HTTP 500",
        )
        d2 = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_selected",
            event_type="case_created",
            payload_json='{"event_type":"case_created"}',
            status="failed",
            attempts=5,
            max_attempts=5,
            next_attempt_at=now,
            last_status_code=500,
            last_error="HTTP 500",
        )
        d3 = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_selected",
            event_type="case_created",
            payload_json='{"event_type":"case_created"}',
            status="delivered",
            attempts=1,
            max_attempts=5,
            next_attempt_at=now,
            delivered_at=now,
        )
        db.add(d1)
        db.add(d2)
        db.add(d3)
        await db.flush()
        missing_id = "missing_delivery_id"
        ids = [d1.delivery_id, d2.delivery_id, d3.delivery_id, missing_id]
        await db.commit()

    replay_resp = await client.post(
        "/api/cases/webhooks/dlq/replay-selected",
        json={"delivery_ids": ids},
    )
    assert replay_resp.status_code == 200
    payload = replay_resp.json()
    assert payload["replayed"] == 2
    assert set(payload["delivery_ids"]) == {d1.delivery_id, d2.delivery_id}
    assert payload["skipped_non_failed_ids"] == [d3.delivery_id]
    assert payload["not_found_ids"] == [missing_id]

    retrying_resp = await client.get("/api/cases/webhooks/deliveries?status=retrying&case_id=case_dlq_selected")
    assert retrying_resp.status_code == 200
    assert len(retrying_resp.json()) == 2


@pytest.mark.asyncio
async def test_case_webhook_dlq_count_endpoint(client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq-count",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_dlq_count_a",
                event_type="case_updated",
                payload_json='{"event_type":"case_updated"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                last_status_code=500,
                last_error="HTTP 500",
                updated_at=now - timedelta(hours=48),
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_dlq_count_b",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="failed",
                attempts=5,
                max_attempts=5,
                next_attempt_at=now,
                last_status_code=500,
                last_error="HTTP 500",
                updated_at=now - timedelta(hours=2),
            )
        )
        db.add(
            CaseWebhookDelivery(
                subscription_id=sub.subscription_id,
                case_id="case_dlq_count_b",
                event_type="case_created",
                payload_json='{"event_type":"case_created"}',
                status="delivered",
                attempts=1,
                max_attempts=5,
                next_attempt_at=now,
                delivered_at=now,
            )
        )
        await db.commit()

    all_resp = await client.get("/api/cases/webhooks/dlq/count")
    assert all_resp.status_code == 200
    assert all_resp.json()["total"] == 2

    filtered_resp = await client.get("/api/cases/webhooks/dlq/count?case_id=case_dlq_count_b")
    assert filtered_resp.status_code == 200
    assert filtered_resp.json()["total"] == 1

    age_filtered_resp = await client.get(
        "/api/cases/webhooks/dlq/count?older_than_hours=24"
    )
    assert age_filtered_resp.status_code == 200
    assert age_filtered_resp.json()["total"] == 1


@pytest.mark.asyncio
async def test_case_webhook_dlq_purge_endpoint(client):
    from datetime import datetime, timedelta, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import AuditEvent, CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))
        await db.execute(delete(AuditEvent))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq-purge",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        old_failed = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_purge",
            event_type="case_updated",
            payload_json='{"event_type":"case_updated"}',
            status="failed",
            attempts=5,
            max_attempts=5,
            next_attempt_at=now,
            last_status_code=500,
            last_error="HTTP 500",
            updated_at=now - timedelta(hours=48),
        )
        recent_failed = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_purge",
            event_type="case_updated",
            payload_json='{"event_type":"case_updated"}',
            status="failed",
            attempts=5,
            max_attempts=5,
            next_attempt_at=now,
            last_status_code=500,
            last_error="HTTP 500",
            updated_at=now - timedelta(hours=2),
        )
        delivered = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_purge",
            event_type="case_created",
            payload_json='{"event_type":"case_created"}',
            status="delivered",
            attempts=1,
            max_attempts=5,
            next_attempt_at=now,
            delivered_at=now,
            updated_at=now,
        )
        db.add(old_failed)
        db.add(recent_failed)
        db.add(delivered)
        await db.commit()

    purge_resp = await client.post(
        "/api/cases/webhooks/dlq/purge?case_id=case_dlq_purge&older_than_hours=24&limit=100"
    )
    assert purge_resp.status_code == 200
    assert purge_resp.json()["deleted"] == 1

    count_resp = await client.get("/api/cases/webhooks/dlq/count?case_id=case_dlq_purge")
    assert count_resp.status_code == 200
    assert count_resp.json()["total"] == 1

    audit_resp = await client.get("/api/audit?category=case_webhook&action=purge")
    assert audit_resp.status_code == 200
    audit_events = audit_resp.json()["events"]
    assert any(
        (event.get("meta") or {}).get("case_id") == "case_dlq_purge"
        and (event.get("meta") or {}).get("deleted") == 1
        for event in audit_events
    )


@pytest.mark.asyncio
async def test_case_webhook_dlq_purge_selected_endpoint(client):
    from datetime import datetime, timezone
    from sqlalchemy import delete

    from app.db.engine import async_session
    from app.db.models import AuditEvent, CaseWebhookDelivery, CaseWebhookSubscription

    async with async_session() as db:
        await db.execute(delete(CaseWebhookDelivery))
        await db.execute(delete(CaseWebhookSubscription))
        await db.execute(delete(AuditEvent))

        sub = CaseWebhookSubscription(
            event_type="*",
            target_url="https://ops.invalid/hook-dlq-purge-selected",
            enabled=True,
        )
        db.add(sub)
        await db.flush()

        now = datetime.now(timezone.utc)
        failed = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_purge_selected",
            event_type="case_updated",
            payload_json='{"event_type":"case_updated"}',
            status="failed",
            attempts=5,
            max_attempts=5,
            next_attempt_at=now,
            last_status_code=500,
            last_error="HTTP 500",
        )
        delivered = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_id="case_dlq_purge_selected",
            event_type="case_created",
            payload_json='{"event_type":"case_created"}',
            status="delivered",
            attempts=1,
            max_attempts=5,
            next_attempt_at=now,
            delivered_at=now,
            updated_at=now,
        )
        db.add(failed)
        db.add(delivered)
        await db.flush()

        missing_id = "missing_dlq_delivery"
        ids = [failed.delivery_id, delivered.delivery_id, missing_id]
        await db.commit()

    resp = await client.post(
        "/api/cases/webhooks/dlq/purge-selected",
        json={"delivery_ids": ids},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["deleted"] == 1
    assert payload["delivery_ids"] == [failed.delivery_id]
    assert payload["skipped_non_failed_ids"] == [delivered.delivery_id]
    assert payload["not_found_ids"] == [missing_id]

    audit_resp = await client.get("/api/audit?category=case_webhook&action=purge_selected")
    assert audit_resp.status_code == 200
    audit_events = audit_resp.json()["events"]
    assert any(
        (event.get("meta") or {}).get("requested_delivery_ids") == ids
        and (event.get("meta") or {}).get("deleted_delivery_ids") == [failed.delivery_id]
        for event in audit_events
    )
