"""Tests for Dead-Letter Queue (DLQ) service and API."""

import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select
from httpx import ASGITransport, AsyncClient

from app.api.auth import _issue_jwt
from app.db.models import DeadLetterQueue
from app.api.dlq import default_retry_handler
from app.db.engine import async_session
from app.main import app
from app.config import settings
from app.services import dlq_service
from app.services import run_service
from app.worker.enqueue import requeue_run


class _TestAsyncClient(AsyncClient):
    async def delete(self, url, *args, json=None, **kwargs):
        if json is not None:
            return await self.request("DELETE", url, *args, json=json, **kwargs)
        return await super().delete(url, *args, **kwargs)


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "dlq-test-secret-with-at-least-32-bytes")


@pytest_asyncio.fixture
async def db_session():
    async with async_session() as db:
        await db.execute(run_service.delete(DeadLetterQueue))
        await db.execute(run_service.delete(run_service.RunJob))
        await db.execute(run_service.delete(run_service.RunEvent))
        await db.execute(run_service.delete(run_service.Run))
        await db.commit()
        try:
            yield db
        finally:
            await db.execute(run_service.delete(DeadLetterQueue))
            await db.execute(run_service.delete(run_service.RunJob))
            await db.execute(run_service.delete(run_service.RunEvent))
            await db.execute(run_service.delete(run_service.Run))
            await db.commit()


@pytest_asyncio.fixture
async def anonymous_client():
    transport = ASGITransport(app=app)
    async with _TestAsyncClient(transport=transport, base_url="http://test", follow_redirects=True) as client:
        yield client


def _auth_headers(role: str) -> dict[str, str]:
    token = _issue_jwt(f"test-{role}", [role], 60, settings.AUTH_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def authorized_client():
    transport = ASGITransport(app=app)
    async with _TestAsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_auth_headers("operator"),
        follow_redirects=True,
    ) as client:
        yield client


@pytest_asyncio.fixture
async def admin_client():
    transport = ASGITransport(app=app)
    async with _TestAsyncClient(
        transport=transport,
        base_url="http://test",
        headers=_auth_headers("admin"),
        follow_redirects=True,
    ) as client:
        yield client


class TestDLQService:
    """Test DLQ service layer."""

    @pytest.mark.asyncio
    async def test_add_to_dlq(self, db_session):
        """Test adding failed event to DLQ."""
        payload = {"case_id": "case_123", "event": "webhook_failed"}
        
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload=payload,
            error_message="Connection timeout",
            error_type="Timeout",
            http_status_code=None,
            entity_type="case",
            entity_id="case_123",
            max_retries=3,
        )
        
        assert dlq_entry.dlq_id is not None
        assert dlq_entry.event_type == "webhook_delivery"
        assert dlq_entry.entity_type == "case"
        assert dlq_entry.entity_id == "case_123"
        assert dlq_entry.error_message == "Connection timeout"
        assert dlq_entry.error_type == "Timeout"
        assert dlq_entry.status == "pending"
        assert dlq_entry.retry_count == 0
        assert dlq_entry.max_retries == 3
        
        # Verify payload is stored as JSON
        stored_payload = json.loads(dlq_entry.payload_json)
        assert stored_payload == payload

    @pytest.mark.asyncio
    async def test_add_non_retriable_to_dlq(self, db_session):
        """Test that non-retriable errors are marked as non_retriable."""
        payload = {"data": "test"}
        
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload=payload,
            error_message="Invalid API key",
            error_type="AuthError",  # Non-retriable
        )
        
        assert dlq_entry.status == "non_retriable"

    @pytest.mark.asyncio
    async def test_get_dlq_messages_no_filter(self, db_session):
        """Test getting all DLQ messages."""
        # Add multiple messages
        for i in range(5):
            await dlq_service.add_to_dlq(
                db=db_session,
                event_type="webhook_delivery",
                payload={"id": i},
                error_message=f"Error {i}",
            )
        
        messages = await dlq_service.get_dlq_messages(db_session)
        assert len(messages) == 5

    @pytest.mark.asyncio
    async def test_get_dlq_messages_with_filters(self, db_session):
        """Test filtering DLQ messages."""
        # Add messages with different types and statuses
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 1},
            error_message="Error 1",
            error_type="Timeout",
        )
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="callback_timeout",
            payload={"id": 2},
            error_message="Error 2",
            error_type="Timeout",
        )
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 3},
            error_message="Auth error",
            error_type="AuthError",  # Non-retriable
        )
        
        # Filter by event_type
        webhook_msgs = await dlq_service.get_dlq_messages(
            db_session, event_type="webhook_delivery"
        )
        assert len(webhook_msgs) == 2
        
        # Filter by status
        non_retriable = await dlq_service.get_dlq_messages(
            db_session, status="non_retriable"
        )
        assert len(non_retriable) == 1
        assert non_retriable[0].error_type == "AuthError"

    @pytest.mark.asyncio
    async def test_count_dlq_messages(self, db_session):
        """Test counting DLQ messages."""
        for i in range(3):
            await dlq_service.add_to_dlq(
                db=db_session,
                event_type="webhook_delivery",
                payload={"id": i},
                error_message=f"Error {i}",
            )
        
        count = await dlq_service.count_dlq_messages(db_session)
        assert count == 3
        
        webhook_count = await dlq_service.count_dlq_messages(
            db_session, event_type="webhook_delivery"
        )
        assert webhook_count == 3

    @pytest.mark.asyncio
    async def test_retry_dlq_message_success(self, db_session):
        """Test successful retry of DLQ message."""
        # Add a message
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
            error_message="Initial failure",
        )
        
        # Mock retry handler that succeeds
        async def mock_handler(event_type, payload, dlq_entry):
            assert event_type == "test_event"
            assert payload == {"test": "data"}
            # Succeeds by not raising
        
        success, message = await dlq_service.retry_dlq_message(
            db_session, dlq_entry.dlq_id, mock_handler
        )
        
        assert success is True
        assert "succeeded" in message.lower()
        
        # Verify status updated
        await db_session.refresh(dlq_entry)
        assert dlq_entry.status == "succeeded"
        assert dlq_entry.retry_count == 1
        assert dlq_entry.succeeded_at is not None

    @pytest.mark.asyncio
    async def test_retry_dlq_message_failure(self, db_session):
        """Test failed retry of DLQ message."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
            error_message="Initial failure",
            max_retries=3,
        )
        
        # Mock retry handler that fails
        async def mock_handler(event_type, payload, dlq_entry):
            raise Exception("Retry failed")
        
        success, message = await dlq_service.retry_dlq_message(
            db_session, dlq_entry.dlq_id, mock_handler
        )
        
        assert success is False
        assert "Retry failed" in message
        
        # Verify status updated
        await db_session.refresh(dlq_entry)
        assert dlq_entry.status == "pending"  # Back to pending for next retry
        assert dlq_entry.retry_count == 1

    @pytest.mark.asyncio
    async def test_retry_dlq_message_exhausted(self, db_session):
        """Test retry when max attempts reached."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
            max_retries=2,
        )
        
        # Manually set retry_count to max
        dlq_entry.retry_count = 2
        await db_session.commit()
        
        async def mock_handler(event_type, payload, dlq_entry):
            raise Exception("Still failing")
        
        success, message = await dlq_service.retry_dlq_message(
            db_session, dlq_entry.dlq_id, mock_handler
        )
        
        assert success is False
        assert "exhausted" in message.lower()

    @pytest.mark.asyncio
    async def test_retry_non_retriable_message(self, db_session):
        """Test that non-retriable messages cannot be retried."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
            error_type="AuthError",  # Non-retriable
        )
        
        async def mock_handler(event_type, payload, dlq_entry):
            pass
        
        success, message = await dlq_service.retry_dlq_message(
            db_session, dlq_entry.dlq_id, mock_handler
        )
        
        assert success is False
        assert "non-retriable" in message.lower()

    @pytest.mark.asyncio
    async def test_bulk_retry_dlq(self, db_session):
        """Test bulk retry with rate limiting."""
        # Add multiple pending messages
        for i in range(5):
            await dlq_service.add_to_dlq(
                db=db_session,
                event_type="webhook_delivery",
                payload={"id": i},
                error_message=f"Error {i}",
            )
        
        # Add one non-retriable (should be skipped)
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 99},
            error_type="AuthError",
        )
        
        # Mock handler that succeeds for even IDs, fails for odd IDs
        async def mock_handler(event_type, payload, dlq_entry):
            if payload["id"] % 2 == 1:
                raise Exception(f"Failed for {payload['id']}")
        
        result = await dlq_service.bulk_retry_dlq(
            db=db_session,
            retry_handler=mock_handler,
            event_type="webhook_delivery",
            max_messages=10,
            rate_limit_per_second=100,  # Fast for testing
        )
        
        assert result["total_processed"] == 5  # Default bulk retry only processes pending messages
        assert result["success_count"] == 3  # IDs 0, 2, 4
        assert result["failed_count"] == 2  # IDs 1, 3
        assert result["skipped_count"] == 0

    @pytest.mark.asyncio
    async def test_purge_dlq_succeeded(self, db_session):
        """Test purging succeeded messages."""
        # Add succeeded message
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
        )
        dlq_entry.status = "succeeded"
        dlq_entry.succeeded_at = datetime.now(timezone.utc)
        await db_session.commit()
        
        # Add pending message (should not be purged)
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "pending"},
        )
        
        purged = await dlq_service.purge_dlq(db_session, status="succeeded")
        assert purged == 1
        
        # Verify pending message still exists
        remaining = await dlq_service.count_dlq_messages(db_session)
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_purge_dlq_by_age(self, db_session):
        """Test purging old messages."""
        # Add old message
        old_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "old"},
        )
        old_entry.failed_at = datetime.now(timezone.utc) - timedelta(days=8)
        await db_session.commit()
        
        # Add recent message
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "recent"},
        )
        
        # Purge messages older than 7 days
        purge_before = datetime.now(timezone.utc) - timedelta(days=7)
        purged = await dlq_service.purge_dlq(
            db_session,
            purge_before=purge_before,
            status="pending",
        )
        assert purged == 1
        
        remaining = await dlq_service.count_dlq_messages(db_session)
        assert remaining == 1

    @pytest.mark.asyncio
    async def test_purge_requires_filter(self, db_session):
        """Test that purge requires at least one filter."""
        with pytest.raises(ValueError, match="At least one filter"):
            await dlq_service.purge_dlq(db_session)

    @pytest.mark.asyncio
    async def test_get_dlq_stats(self, db_session):
        """Test DLQ statistics."""
        # Add various messages
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 1},
            error_message="Error 1",
        )
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="callback_timeout",
            payload={"id": 2},
            error_message="Error 2",
        )
        
        # Add one succeeded
        succeeded = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 3},
        )
        succeeded.status = "succeeded"
        await db_session.commit()
        
        stats = await dlq_service.get_dlq_stats(db_session)
        
        assert stats["total"] == 3
        assert stats["by_status"]["pending"] == 2
        assert stats["by_status"]["succeeded"] == 1
        assert stats["by_event_type"]["webhook_delivery"] == 2
        assert stats["by_event_type"]["callback_timeout"] == 1
        assert stats["pending_last_hour"] == 2
        assert stats["pending_last_day"] == 2

    @pytest.mark.asyncio
    async def test_callback_timeout_retry_requeues_run(self, db_session):
        """Callback-timeout DLQ retry should prepare and requeue the failed run."""
        run = await run_service.create_run(
            db_session,
            procedure_id="callback_retry_proc",
            procedure_version="1.0.0",
            input_vars={},
        )
        await run_service.update_run_status(
            db_session,
            run.run_id,
            "failed",
            last_node_id="node-callback",
            last_step_id="step-callback",
            error_message="Workflow webhook callback timed out after 5 minutes.",
        )
        await requeue_run(db_session, run.run_id)
        await db_session.commit()

        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="callback_timeout",
            payload={
                "run_id": run.run_id,
                "timeout_minutes": 5,
                "resume_node_id": "node-callback",
                "resume_step_id": "step-callback",
            },
            error_message="Workflow webhook callback timed out after 5 minutes.",
            error_type="Timeout",
            entity_type="run",
            entity_id=run.run_id,
        )

        success, message = await dlq_service.retry_dlq_message(
            db_session,
            dlq_entry.dlq_id,
            default_retry_handler,
        )

        assert success is True
        assert "succeeded" in message.lower()

        await db_session.refresh(dlq_entry)
        assert dlq_entry.status == "succeeded"

        async with async_session() as verify_db:
            refreshed_run = await run_service.get_run(verify_db, run.run_id)
            assert refreshed_run is not None
            assert refreshed_run.status == "created"
            assert refreshed_run.ended_at is None
            assert refreshed_run.error_message is None

        retry_events = await run_service.list_events(db_session, run.run_id)
        event_types = [event.event_type for event in retry_events]
        assert "run_retry_requested" in event_types
        assert "callback_timeout_retry_requested" in event_types

    @pytest.mark.asyncio
    async def test_auto_fail_stalled_workflows_enrolls_callback_timeout_in_dlq(self, db_session):
        """Stalled workflow timeout should create a callback_timeout DLQ entry."""
        run = await run_service.create_run(
            db_session,
            procedure_id="timeout_proc",
            procedure_version="1.0.0",
            input_vars={},
        )
        await run_service.update_run_status(db_session, run.run_id, "paused", last_node_id="node-wait")
        await run_service.emit_event(
            db_session,
            run.run_id,
            "workflow_delegated",
            node_id="node-wait",
            step_id="step-wait",
            payload={
                "resume_node_id": "node-wait",
                "resume_step_id": "step-wait",
                "callback_url": "http://callback.local",
                "action": "workflow_action",
                "agent_url": "http://agent.local",
            },
        )
        await db_session.commit()

        failed_runs = await run_service.auto_fail_stalled_workflows(db_session, timeout_minutes=0)
        assert run.run_id in failed_runs

        refreshed_run = await run_service.get_run(db_session, run.run_id)
        assert refreshed_run is not None
        assert refreshed_run.status == "failed"

        dlq_rows = await dlq_service.get_dlq_messages(db_session, event_type="callback_timeout", entity_id=run.run_id)
        assert len(dlq_rows) == 1
        payload = json.loads(dlq_rows[0].payload_json)
        assert payload["run_id"] == run.run_id
        assert payload["resume_node_id"] == "node-wait"
        assert payload["resume_step_id"] == "step-wait"
        assert dlq_rows[0].entity_type == "run"
        assert dlq_rows[0].status == "pending"


class TestDLQAPI:
    """Test DLQ API endpoints."""

    @pytest.mark.asyncio
    async def test_list_dlq_messages(self, authorized_client, db_session):
        """Test GET /api/dlq endpoint."""
        # Add test messages
        for i in range(3):
            await dlq_service.add_to_dlq(
                db=db_session,
                event_type="webhook_delivery",
                payload={"id": i},
                error_message=f"Error {i}",
            )
        
        response = await authorized_client.get("/api/dlq")
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 3
        assert len(data["messages"]) == 3
        assert data["limit"] == 100
        assert data["offset"] == 0

    @pytest.mark.asyncio
    async def test_list_dlq_with_filters(self, authorized_client, db_session):
        """Test filtering DLQ messages via API."""
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"id": 1},
        )
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="callback_timeout",
            payload={"id": 2},
        )
        
        response = await authorized_client.get(
            "/api/dlq?event_type=webhook_delivery"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["total"] == 1

    @pytest.mark.asyncio
    async def test_get_dlq_stats_api(self, authorized_client, db_session):
        """Test GET /api/dlq/stats endpoint."""
        await dlq_service.add_to_dlq(
            db=db_session,
            event_type="webhook_delivery",
            payload={"test": "data"},
        )
        
        response = await authorized_client.get("/api/dlq/stats")
        assert response.status_code == 200
        data = response.json()
        
        assert data["total"] == 1
        assert "by_status" in data
        assert "by_event_type" in data

    @pytest.mark.asyncio
    async def test_retry_single_message_api(self, admin_client, db_session):
        """Test POST /api/dlq/{dlq_id}/retry endpoint."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
        )
        
        # Mock the retry handler to succeed
        with patch("app.api.dlq.default_retry_handler", new_callable=AsyncMock):
            response = await admin_client.post(f"/api/dlq/{dlq_entry.dlq_id}/retry")
            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True

    @pytest.mark.asyncio
    async def test_retry_callback_timeout_message_api(self, admin_client, db_session):
        """Test callback-timeout replay through the DLQ API."""
        run = await run_service.create_run(
            db_session,
            procedure_id="callback_retry_api_proc",
            procedure_version="1.0.0",
            input_vars={},
        )
        await run_service.update_run_status(
            db_session,
            run.run_id,
            "failed",
            last_node_id="node-api",
            last_step_id="step-api",
            error_message="Workflow webhook callback timed out after 3 minutes.",
        )
        await requeue_run(db_session, run.run_id)
        await db_session.commit()

        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="callback_timeout",
            payload={
                "run_id": run.run_id,
                "timeout_minutes": 3,
                "resume_node_id": "node-api",
                "resume_step_id": "step-api",
            },
            error_message="Workflow webhook callback timed out after 3 minutes.",
            error_type="Timeout",
            entity_type="run",
            entity_id=run.run_id,
        )

        response = await admin_client.post(f"/api/dlq/{dlq_entry.dlq_id}/retry")
        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True

        async with async_session() as verify_db:
            refreshed_run = await run_service.get_run(verify_db, run.run_id)
            assert refreshed_run is not None
            assert refreshed_run.status == "created"

    @pytest.mark.asyncio
    async def test_bulk_retry_api(self, admin_client, db_session):
        """Test POST /api/dlq/bulk-retry endpoint."""
        for i in range(3):
            await dlq_service.add_to_dlq(
                db=db_session,
                event_type="webhook_delivery",
                payload={"id": i},
            )
        
        with patch("app.api.dlq.default_retry_handler", new_callable=AsyncMock):
            response = await admin_client.post(
                "/api/dlq/bulk-retry",
                json={
                    "event_type": "webhook_delivery",
                    "max_messages": 10,
                    "rate_limit_per_second": 100,
                },
            )
            assert response.status_code == 200
            data = response.json()
            assert data["total_processed"] == 3

    @pytest.mark.asyncio
    async def test_purge_dlq_api(self, admin_client, db_session):
        """Test DELETE /api/dlq/purge endpoint."""
        succeeded = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
        )
        succeeded.status = "succeeded"
        await db_session.commit()
        
        response = await admin_client.delete(
            "/api/dlq/purge",
            json={"status": "succeeded"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["purged_count"] == 1

    @pytest.mark.asyncio
    async def test_delete_single_message_api(self, admin_client, db_session):
        """Test DELETE /api/dlq/{dlq_id} endpoint."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
        )
        
        response = await admin_client.delete(f"/api/dlq/{dlq_entry.dlq_id}")
        assert response.status_code == 200
        data = response.json()
        assert data["deleted"] is True
        
        # Verify deleted
        count = await dlq_service.count_dlq_messages(db_session)
        assert count == 0

    @pytest.mark.asyncio
    async def test_dlq_requires_auth(self, anonymous_client):
        """Test that DLQ endpoints require authentication."""
        response = await anonymous_client.get("/api/dlq")
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_dlq_admin_endpoints_require_admin(self, authorized_client, db_session):
        """Test that admin operations require admin role."""
        dlq_entry = await dlq_service.add_to_dlq(
            db=db_session,
            event_type="test_event",
            payload={"test": "data"},
        )
        
        # Non-admin user should not be able to retry
        response = await authorized_client.post(f"/api/dlq/{dlq_entry.dlq_id}/retry")
        assert response.status_code == 403
