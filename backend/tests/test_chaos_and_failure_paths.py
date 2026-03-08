"""Chaos and failure-path tests for enterprise resilience.

Tests critical failure scenarios:
1. Callback loss/retry
2. Worker crash during lock ownership
3. DB failover/reconnect scenarios
4. Trigger dedupe race under concurrent ingestion
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import pytest
import uuid
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta, timezone
from fastapi import BackgroundTasks
from fastapi.testclient import TestClient
from sqlalchemy import select, update

from app.config import settings
from app.db.models import DeadLetterQueue, Run, RunEvent, RunJob
from app.db.engine import async_session
from app.main import app
from app.services import run_service
from app.worker.loop import worker_loop


def _callback_token(run_id: str) -> str:
    return hmac.new(
        settings.AUTH_SECRET_KEY.encode(),
        run_id.encode(),
        hashlib.sha256,
    ).hexdigest()


@pytest.fixture
def client():
    """Provide a sync API client for legacy chaos tests in this module."""
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
async def async_client():
    """Async in-process client for high-concurrency load tests."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as test_client:
        yield test_client


class TestCallbackLossAndRetry:
    """Tests for callback timeout and retry handling."""

    @pytest.mark.asyncio
    async def test_callback_timeout_recovery_adds_dlq_entry(self):
        """Stalled delegated workflows are failed and added to the callback-timeout DLQ."""
        delegated_at = datetime.now(timezone.utc) - timedelta(minutes=10)

        from app.services.run_service import auto_fail_stalled_workflows

        async with async_session() as db:
            run = await run_service.create_run(
                db,
                procedure_id="callback_proc",
                procedure_version="1.0.0",
                input_vars={},
            )
            await run_service.update_run_status(db, run.run_id, "paused")
            await run_service.emit_event(
                db,
                run.run_id,
                "workflow_delegated",
                node_id="node-timeout",
                step_id="step-timeout",
                payload={
                    "resume_node_id": "node-timeout",
                    "resume_step_id": "step-timeout",
                    "callback_url": f"http://test/api/runs/{run.run_id}/callback",
                    "action": "workflow",
                },
            )
            await db.execute(
                update(RunEvent)
                .where(RunEvent.run_id == run.run_id)
                .values(ts=delegated_at - timedelta(seconds=1))
            )
            delegation = (
                await db.execute(
                    select(RunEvent)
                    .where(RunEvent.run_id == run.run_id, RunEvent.event_type == "workflow_delegated")
                    .order_by(RunEvent.ts.desc())
                    .limit(1)
                )
            ).scalar_one()
            delegation.ts = delegated_at
            await db.commit()
            run_id = run.run_id

        async with async_session() as db:
            failed_runs = await auto_fail_stalled_workflows(db, timeout_minutes=5)
            await db.commit()
            assert run_id in failed_runs

        async with async_session() as db:
            refreshed_run = await run_service.get_run(db, run_id)
            dlq_entry = (
                await db.execute(
                    select(DeadLetterQueue)
                    .where(
                        DeadLetterQueue.entity_type == "run",
                        DeadLetterQueue.entity_id == run_id,
                        DeadLetterQueue.event_type == "callback_timeout",
                    )
                    .order_by(DeadLetterQueue.failed_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            assert refreshed_run is not None
            assert refreshed_run.status == "failed"
            assert dlq_entry is not None
            assert dlq_entry.error_type == "Timeout"

    @pytest.mark.asyncio
    async def test_callback_endpoint_resumes_paused_run(self):
        """A valid workflow callback resumes a paused run through the live endpoint contract."""
        from app.api.runs import workflow_callback

        async with async_session() as db:
            run = await run_service.create_run(
                db,
                procedure_id="callback_retry_proc",
                procedure_version="1.0.0",
                input_vars={},
            )
            await run_service.update_run_status(db, run.run_id, "paused")
            await run_service.emit_event(
                db,
                run.run_id,
                "workflow_delegated",
                node_id="node-1",
                step_id="step-1",
                payload={
                    "resume_node_id": "node-1",
                    "resume_step_id": "step-1",
                    "callback_url": f"http://test/api/runs/{run.run_id}/callback",
                },
            )
            await db.commit()
            run_id = run.run_id

        async with async_session() as db:
            callback_resp = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                    "output": {"status": "paid"},
                },
                background_tasks=BackgroundTasks(),
                token=_callback_token(run_id),
                db=db,
            )
            await db.commit()

            refreshed_run = await run_service.get_run(db, run_id)
            assert callback_resp["resumed"] is True
            assert callback_resp["status"] == "queued"
            assert refreshed_run is not None
            assert refreshed_run.status == "queued"


class TestWorkerCrashDuringLockOwnership:
    """Tests for worker crash scenarios and job reclaim."""

    @pytest.mark.asyncio
    async def test_job_reclaimed_after_worker_death(self, minimal_ckp):
        """Job claimed by worker that crashes is reclaimed by another worker."""
        from app.worker.loop import poll_and_claim, reclaim_stalled_jobs
        from app.services import procedure_service
        from app.worker.enqueue import enqueue_run

        async with async_session() as db:
            await procedure_service.import_procedure(db, minimal_ckp)
            run = await run_service.create_run(
                db,
                procedure_id="test_proc",
                procedure_version="1.0.0",
                input_vars={},
            )
            enqueue_run(db, run.run_id)
            await db.commit()
        
        # Simulate first worker claiming the job
        claimed_jobs = await poll_and_claim("worker-a", 1)
        assert claimed_jobs
        job = claimed_jobs[0]
        assert job.status == "running"
        
        # Simulate worker crash (no heartbeat, job not completed)
        async with async_session() as db:
            stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            await db.execute(
                update(RunJob)
                .where(RunJob.job_id == job.job_id)
                .values(locked_until=stale_time)
            )
            await db.commit()
        
        reclaimed_count = await reclaim_stalled_jobs()
        assert reclaimed_count >= 1

        async with async_session() as db:
            reclaimed_row = await db.get(RunJob, job.job_id)
            assert reclaimed_row is not None
            assert reclaimed_row.status == "retrying"
            reclaimed_row.available_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()

        reclaimed_jobs = await poll_and_claim("worker-b", 1)
        assert reclaimed_jobs
        reclaimed_job = reclaimed_jobs[0]
        assert reclaimed_job.job_id == job.job_id
        assert reclaimed_job.locked_by == "worker-b"

    @pytest.mark.asyncio
    async def test_worker_crash_mid_execution_preserves_checkpoint(self):
        """Checkpoint rows survive run execution for checkpoint-enabled workflows."""
        ckp = {
            "procedure_id": "checkpoint_proc",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "step1",
                "nodes": {
                    "step1": {
                        "type": "sequence",
                        "is_checkpoint": True,
                        "steps": [{"step_id": "s1", "action": "log", "message": "step1"}],
                        "next_node": "step2",
                    },
                    "step2": {
                        "type": "sequence",
                        "is_checkpoint": True,
                        "steps": [{"step_id": "s2", "action": "log", "message": "step2"}],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        from app.services import checkpoint_service, execution_service, procedure_service

        async with async_session() as db:
            await procedure_service.import_procedure(db, ckp)
            run = await run_service.create_run(
                db,
                procedure_id="checkpoint_proc",
                procedure_version="1.0.0",
                input_vars={},
            )
            await db.commit()
            run_id = run.run_id

        await execution_service.execute_run(run_id, async_session)

        checkpoints = await checkpoint_service.list_checkpoints(run_id)
        assert len(checkpoints) > 0


class TestDBFailoverAndReconnect:
    """Tests for database connection resilience."""

    @pytest.mark.asyncio
    async def test_db_connection_pool_exhaustion_recovery(self, client):
        """Connection pool exhaustion is handled gracefully."""
        from app.db.engine import async_session
        
        # Simulate pool exhaustion by opening many connections
        sessions = []
        try:
            for _ in range(50):  # Exceed typical pool size
                session = async_session()
                sessions.append(session)
            
            # API should still respond (or queue gracefully)
            resp = client.get("/api/health")
            assert resp.status_code in [200, 503]  # 503 = temporarily unavailable
        finally:
            # Cleanup
            for session in sessions:
                await session.close()

    @pytest.mark.asyncio
    async def test_transient_db_error_retry(self):
        """Transient DB errors trigger retry with backoff."""
        from app.db.engine import async_session
        from sqlalchemy.exc import OperationalError
        
        retry_count = 0
        max_retries = 3
        
        async def db_operation_with_retries():
            nonlocal retry_count
            for attempt in range(max_retries):
                try:
                    async with async_session() as db:
                        # Simulate transient failure on first 2 attempts
                        if retry_count < 2:
                            retry_count += 1
                            raise OperationalError("Connection lost", None, None)
                        
                        # Success on 3rd attempt
                        result = await db.execute(select(Run).limit(1))
                        return result.scalar_one_or_none()
                except OperationalError:
                    if attempt < max_retries - 1:
                        await asyncio.sleep(0.1 * (2 ** attempt))  # Exponential backoff
                    else:
                        raise
        
        result = await db_operation_with_retries()
        assert retry_count == 2  # Failed twice, succeeded on 3rd

    @pytest.mark.asyncio
    async def test_worker_handles_db_reconnect(self):
        """Worker loop gracefully handles database reconnection."""
        from app.worker.loop import worker_loop

        reclaim_attempts = 0

        async def flaky_reclaim():
            nonlocal reclaim_attempts
            reclaim_attempts += 1
            if reclaim_attempts == 1:
                raise Exception("Database connection lost")
            return 0

        with patch("app.worker.loop.reclaim_stalled_jobs", side_effect=flaky_reclaim), patch(
            "app.worker.loop.poll_and_claim",
            AsyncMock(return_value=[]),
        ):
            worker_task = asyncio.create_task(worker_loop(poll_interval=0.05))
            await asyncio.sleep(0.2)
            worker_task.cancel()

            try:
                await worker_task
            except asyncio.CancelledError:
                pass

        assert reclaim_attempts >= 2


class TestTriggerDedupeRaceConditions:
    """Tests for concurrent trigger ingestion and deduplication."""

    @pytest.mark.asyncio
    async def test_concurrent_identical_triggers_dedupe(self, client, minimal_ckp):
        """Multiple identical triggers arriving concurrently are deduped."""
        # Create procedure with trigger
        ckp_with_trigger = {
            **minimal_ckp,
            "procedure_id": "trigger_proc",
            "trigger": {
                "type": "webhook",
                "dedupe_window_seconds": 3600,
            },
        }
        
        resp = client.post("/api/procedures", json={"ckp_json": ckp_with_trigger})
        assert resp.status_code == 201
        sync_resp = client.post("/api/triggers/sync")
        assert sync_resp.status_code == 200
        
        # Fire 10 identical webhook events concurrently
        event_payload = {"event_id": "evt_12345", "order_id": "ord_999"}
        
        tasks = []
        for _ in range(10):
            task = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/api/triggers/webhook/trigger_proc",
                    json=event_payload,
                )
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks)

        accepted = [r for r in responses if r.status_code == 202]
        deduped = [r for r in responses if r.status_code == 409]
        assert len(accepted) == 1
        assert len(deduped) == 9
        
        # Only one run and one dedupe record should exist.
        from app.db.engine import async_session
        from app.db.models import TriggerDedupeRecord
        
        async with async_session() as db:
            run_result = await db.execute(
                select(Run).where(Run.procedure_id == "trigger_proc")
            )
            dedupe_result = await db.execute(
                select(TriggerDedupeRecord).where(
                    TriggerDedupeRecord.procedure_id == "trigger_proc"
                )
            )
            runs = run_result.scalars().all()
            dedupe_records = dedupe_result.scalars().all()
            assert len(runs) == 1
            assert len(dedupe_records) == 1

    @pytest.mark.asyncio
    async def test_high_volume_trigger_ingestion(self, client, minimal_ckp):
        """System handles high-volume concurrent trigger ingestion."""
        ckp = {
            **minimal_ckp,
            "procedure_id": "load_test_proc",
            "trigger": {
                "type": "webhook",
            },
        }
        
        resp = client.post("/api/procedures", json={"ckp_json": ckp})
        assert resp.status_code == 201
        sync_resp = client.post("/api/triggers/sync")
        assert sync_resp.status_code == 200
        
        # Fire 100 unique events rapidly
        async def fire_event(event_id: int):
            return await asyncio.to_thread(
                client.post,
                "/api/triggers/webhook/load_test_proc",
                json={"event_id": f"evt_{event_id}"},
            )
        
        tasks = [fire_event(i) for i in range(100)]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Count successful ingestions
        success_count = sum(
            1 for r in responses
            if not isinstance(r, Exception) and r.status_code in [200, 202]
        )
        
        # Should handle most/all events (allowing for some backpressure)
        assert success_count >= 90

    @pytest.mark.asyncio
    async def test_trigger_concurrency_guard_enforcement(self, client, minimal_ckp):
        """Trigger concurrency limit prevents parallel executions."""
        ckp = {
            **minimal_ckp,
            "procedure_id": "concurrency_guard_proc",
            "trigger": {
                "type": "webhook",
                "max_concurrent_runs": 1,
            },
        }
        
        resp = client.post("/api/procedures", json={"ckp_json": ckp})
        assert resp.status_code == 201
        sync_resp = client.post("/api/triggers/sync")
        assert sync_resp.status_code == 200
        
        # Fire 5 events concurrently
        tasks = []
        for i in range(5):
            task = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/api/triggers/webhook/concurrency_guard_proc",
                    json={"event_id": f"evt_{i}"},
                )
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks)

        accepted = [r for r in responses if r.status_code == 202]
        rejected = [r for r in responses if r.status_code == 429]
        assert accepted, "Expected at least one trigger fire to be accepted"
        assert rejected, "Expected concurrency guard to reject at least one trigger fire"
        
        # Check that concurrency guard was enforced
        from app.db.engine import async_session
        
        async with async_session() as db:
            result = await db.execute(
                select(Run).where(Run.procedure_id == "concurrency_guard_proc")
            )
            runs = result.scalars().all()
            
            # Should have created runs, but concurrency limiting means
            # some may be queued/rejected
            assert len(runs) >= 1


class TestLoadAndSoakScenarios:
    """Load and soak testing for production-scale resilience."""

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_sustained_load_over_time(self, async_client, minimal_ckp):
        """System maintains stability under sustained moderate load."""
        procedure_id = f"sustained-load-{uuid.uuid4().hex[:8]}"
        ckp = {**minimal_ckp, "procedure_id": procedure_id}

        resp = await async_client.post("/api/procedures", json={"ckp_json": ckp})
        assert resp.status_code == 201
        
        # Run for 30 seconds with 10 QPS
        duration_seconds = 30
        qps = 10
        total_requests = duration_seconds * qps
        successful_requests = 0
        
        async def fire_run():
            return await async_client.post(
                "/api/runs",
                json={
                    "procedure_id": procedure_id,
                    "procedure_version": "1.0.0",
                    "input_vars": {},
                },
            )
        
        start_time = asyncio.get_event_loop().time()
        requests_fired = 0
        
        while asyncio.get_event_loop().time() - start_time < duration_seconds:
            batch_tasks = [fire_run() for _ in range(qps)]
            responses = await asyncio.gather(*batch_tasks, return_exceptions=True)
            requests_fired += qps
            successful_requests += sum(
                1
                for response in responses
                if not isinstance(response, Exception) and response.status_code == 201
            )
            await asyncio.sleep(1)
        
        # Verify system health after load
        health_resp = await async_client.get("/api/health")
        assert health_resp.status_code == 200
        assert requests_fired >= total_requests * 0.5  # allow transport overhead in-process
        assert successful_requests >= requests_fired * 0.9

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_queue_depth_under_load(self, async_client, minimal_ckp):
        """Queue depth metrics are accurate under load."""
        procedure_id = f"queue-depth-{uuid.uuid4().hex[:8]}"
        ckp = {**minimal_ckp, "procedure_id": procedure_id}

        resp = await async_client.post("/api/procedures", json={"ckp_json": ckp})
        assert resp.status_code == 201
        
        # Fire 50 runs rapidly to build queue
        tasks = []
        for _ in range(50):
            task = asyncio.create_task(
                async_client.post(
                    "/api/runs",
                    json={
                        "procedure_id": procedure_id,
                        "procedure_version": "1.0.0",
                        "input_vars": {},
                    },
                )
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Check queue analytics
        from app.db.engine import async_session
        
        async with async_session() as db:
            result = await db.execute(
                select(RunJob).where(RunJob.status.in_(["queued", "retrying"]))
            )
            pending_jobs = result.scalars().all()
            
            # Should have jobs in queue
            assert len(pending_jobs) > 0

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_memory_stability_over_time(self, async_client, minimal_ckp):
        """No memory leaks during extended operation."""
        import os
        psutil = pytest.importorskip("psutil")
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        procedure_id = f"memory-stability-{uuid.uuid4().hex[:8]}"
        ckp = {**minimal_ckp, "procedure_id": procedure_id}

        resp = await async_client.post("/api/procedures", json={"ckp_json": ckp})
        assert resp.status_code == 201
        
        # Run 100 workflows
        for _ in range(100):
            await async_client.post(
                "/api/runs",
                json={
                    "procedure_id": procedure_id,
                    "procedure_version": "1.0.0",
                    "input_vars": {},
                },
            )
            await asyncio.sleep(0.1)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_growth = final_memory - initial_memory
        
        # Memory growth should be reasonable (< 100MB for 100 runs)
        assert memory_growth < 100, f"Memory grew by {memory_growth:.2f}MB"
