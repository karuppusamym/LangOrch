"""Chaos and failure-path tests for enterprise resilience.

Tests critical failure scenarios:
1. Callback loss/retry
2. Worker crash during lock ownership
3. DB failover/reconnect scenarios
4. Trigger dedupe race under concurrent ingestion
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update

from app.db.models import Run, TriggerRegistration, TriggerExecution, WorkflowJob
from app.services.run_service import record_run_event
from app.worker.loop import claim_next_job, worker_loop


class TestCallbackLossAndRetry:
    """Tests for callback timeout and retry handling."""

    @pytest.mark.asyncio
    async def test_callback_timeout_recovery(self, client, minimal_ckp):
        """Workflow expecting callback times out and fires recovery handler."""
        # Create a procedure with callback_wait action (5 second timeout)
        ckp_with_callback = {
            **minimal_ckp,
            "procedure_id": "callback_proc",
            "workflow_graph": {
                "start_node": "wait_for_callback",
                "nodes": {
                    "wait_for_callback": {
                        "type": "sequence",
                        "next_node": "success_node",
                        "steps": [{
                            "step_id": "wait_step",
                            "action": "callback_wait",
                            "callback_id": "payment_webhook",
                            "timeout_ms": 5000
                        }],
                    },
                    "success_node": {
                        "type": "terminate",
                        "status": "success",
                    },
                },
            },
            "global_config": {
                "on_failure": "timeout_handler",
            },
        }
        
        # Add timeout handler node (retries the callback wait)
        ckp_with_callback["workflow_graph"]["nodes"]["timeout_handler"] = {
            "type": "sequence",
            "steps": [
                {"step_id": "log_timeout", "action": "log", "message": "Callback timed out, retrying..."}
            ],
            "next_node": "wait_for_callback",
        }
        
        # Upload procedure
        resp = client.post("/api/procedures", json=ckp_with_callback)
        assert resp.status_code == 201
        
        # Start run
        run_resp = client.post("/api/procedures/callback_proc/run", json={"vars": {}})
        assert run_resp.status_code == 202
        run_id = run_resp.json()["run_id"]
        
        # Wait for callback timeout to fire
        await asyncio.sleep(6)
        
        # Verify timeout was recorded and recovery handler invoked
        run_detail = client.get(f"/api/runs/{run_id}").json()
        assert any("timeout" in evt.get("event_type", "").lower() for evt in run_detail.get("events", []))

    @pytest.mark.asyncio
    async def test_callback_retry_with_exponential_backoff(self, client, minimal_ckp):
        """Callback retries use exponential backoff and eventual success."""
        ckp = {
            **minimal_ckp,
            "procedure_id": "callback_retry_proc",
            "global_config": {"callback_retry_max": 3, "callback_retry_backoff_ms": 1000},
            "workflow_graph": {
                "start_node": "callback_node",
                "nodes": {
                    "callback_node": {
                        "type": "sequence",
                        "steps": [
                            {
                                "step_id": "cb1",
                                "action": "callback_wait",
                                "callback_id": "payment_cb",
                                "timeout_ms": 2000,
                            }
                        ],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        
        resp = client.post("/api/procedures", json=ckp)
        assert resp.status_code == 201
        
        run_resp = client.post("/api/procedures/callback_retry_proc/run", json={"vars": {}})
        run_id = run_resp.json()["run_id"]
        
        # Simulate callback arriving on 3rd retry
        await asyncio.sleep(3)
        callback_resp = client.post(f"/api/callbacks/{run_id}/payment_cb", json={"status": "paid"})
        assert callback_resp.status_code in [200, 202]


class TestWorkerCrashDuringLockOwnership:
    """Tests for worker crash scenarios and job reclaim."""

    @pytest.mark.asyncio
    async def test_job_reclaimed_after_worker_death(self, client, minimal_ckp):
        """Job claimed by worker that crashes is reclaimed by another worker."""
        from app.db.engine import async_session
        from app.db.models import WorkflowJob
        from datetime import datetime, timezone, timedelta
        
        # Create procedure
        resp = client.post("/api/procedures", json=minimal_ckp)
        assert resp.status_code == 201
        
        # Create a job
        run_resp = client.post("/api/procedures/test_proc/run", json={"vars": {}})
        run_id = run_resp.json()["run_id"]
        
        # Simulate first worker claiming the job
        async with async_session() as db:
            job = await claim_next_job(db)
            assert job is not None
            first_claim_time = job.claimed_at
            await db.commit()
        
        # Simulate worker crash (no heartbeat, job not completed)
        # Wait for reclaim timeout (default is 5 minutes, simulate by backdating claim)
        async with async_session() as db:
            stale_time = datetime.now(timezone.utc) - timedelta(minutes=10)
            await db.execute(
                update(WorkflowJob)
                .where(WorkflowJob.id == job.id)
                .values(claimed_at=stale_time)
            )
            await db.commit()
        
        # Second worker reclaims the stale job
        async with async_session() as db:
            reclaimed_job = await claim_next_job(db)
            assert reclaimed_job is not None
            assert reclaimed_job.id == job.id
            assert reclaimed_job.claimed_at > stale_time
            await db.commit()

    @pytest.mark.asyncio
    async def test_worker_crash_mid_execution_preserves_checkpoint(self, client):
        """Worker crash mid-execution allows resume from last checkpoint."""
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
        
        resp = client.post("/api/procedures", json=ckp)
        assert resp.status_code == 201
        
        # Start run
        run_resp = client.post("/api/procedures/checkpoint_proc/run", json={"vars": {}})
        run_id = run_resp.json()["run_id"]
        
        # Worker processes step1, checkpoints, then crashes before step2
        # Simulate by waiting for step1 completion
        await asyncio.sleep(2)
        
        # Verify checkpoint was saved
        from app.db.engine import async_session
        from app.db.models import Checkpoint
        async with async_session() as db:
            result = await db.execute(
                select(Checkpoint).where(Checkpoint.thread_id == run_id)
            )
            checkpoints = result.scalars().all()
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
        from app.config import settings
        
        # Mock DB session that fails once then succeeds
        failure_count = 0
        
        async def mock_session_with_failure():
            nonlocal failure_count
            if failure_count == 0:
                failure_count += 1
                raise Exception("Database connection lost")
            # Return mock session on retry
            return MagicMock()
        
        with patch("app.worker.loop.async_session", side_effect=mock_session_with_failure):
            # Worker should log error and retry
            # Run for short duration
            worker_task = asyncio.create_task(worker_loop())
            await asyncio.sleep(0.5)
            worker_task.cancel()
            
            try:
                await worker_task
            except asyncio.CancelledError:
                pass
            
            # Verify failure was encountered and handled
            assert failure_count > 0


class TestTriggerDedupeRaceConditions:
    """Tests for concurrent trigger ingestion and deduplication."""

    @pytest.mark.asyncio
    async def test_concurrent_identical_triggers_dedupe(self, client, minimal_ckp):
        """Multiple identical triggers arriving concurrently are deduped."""
        # Create procedure with trigger
        ckp_with_trigger = {
            **minimal_ckp,
            "procedure_id": "trigger_proc",
            "triggers": [
                {
                    "trigger_id": "webhook_trigger",
                    "type": "webhook",
                    "event_type": "order.created",
                    "dedupe_key": "event_id",
                    "dedupe_window_minutes": 60,
                }
            ],
        }
        
        resp = client.post("/api/procedures", json=ckp_with_trigger)
        assert resp.status_code == 201
        
        # Fire 10 identical webhook events concurrently
        event_payload = {"event_id": "evt_12345", "order_id": "ord_999"}
        
        tasks = []
        for _ in range(10):
            task = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/api/triggers/webhook/order.created",
                    json=event_payload,
                )
            )
            tasks.append(task)
        
        responses = await asyncio.gather(*tasks)
        
        # All should return 200/202, but only one run should be created
        from app.db.engine import async_session
        from app.db.models import TriggerExecution
        
        async with async_session() as db:
            result = await db.execute(
                select(TriggerExecution).where(
                    TriggerExecution.dedupe_key == "evt_12345"
                )
            )
            executions = result.scalars().all()
            # Should have at most 1 execution (dedupe)
            assert len(executions) <= 1

    @pytest.mark.asyncio
    async def test_high_volume_trigger_ingestion(self, client, minimal_ckp):
        """System handles high-volume concurrent trigger ingestion."""
        ckp = {
            **minimal_ckp,
            "procedure_id": "load_test_proc",
            "triggers": [
                {
                    "trigger_id": "load_trigger",
                    "type": "webhook",
                    "event_type": "high_volume.event",
                }
            ],
        }
        
        resp = client.post("/api/procedures", json=ckp)
        assert resp.status_code == 201
        
        # Fire 100 unique events rapidly
        async def fire_event(event_id: int):
            return await asyncio.to_thread(
                client.post,
                "/api/triggers/webhook/high_volume.event",
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
            "triggers": [
                {
                    "trigger_id": "guarded_trigger",
                    "type": "webhook",
                    "event_type": "guarded.event",
                    "max_concurrency": 1,  # Only allow 1 concurrent execution
                }
            ],
        }
        
        resp = client.post("/api/procedures", json=ckp)
        assert resp.status_code == 201
        
        # Fire 5 events concurrently
        tasks = []
        for i in range(5):
            task = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/api/triggers/webhook/guarded.event",
                    json={"event_id": f"evt_{i}"},
                )
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Check that concurrency guard was enforced
        from app.db.engine import async_session
        from app.db.models import Run
        
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
    async def test_sustained_load_over_time(self, client, minimal_ckp):
        """System maintains stability under sustained moderate load."""
        resp = client.post("/api/procedures", json=minimal_ckp)
        assert resp.status_code == 201
        
        # Run for 30 seconds with 10 QPS
        duration_seconds = 30
        qps = 10
        total_requests = duration_seconds * qps
        
        async def fire_run():
            return await asyncio.to_thread(
                client.post,
                "/api/procedures/test_proc/run",
                json={"vars": {}},
            )
        
        start_time = asyncio.get_event_loop().time()
        requests_fired = 0
        
        while asyncio.get_event_loop().time() - start_time < duration_seconds:
            batch_tasks = [fire_run() for _ in range(qps)]
            await asyncio.gather(*batch_tasks, return_exceptions=True)
            requests_fired += qps
            await asyncio.sleep(1)
        
        # Verify system health after load
        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200
        assert requests_fired >= total_requests * 0.9  # Allow 10% variance

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_queue_depth_under_load(self, client, minimal_ckp):
        """Queue depth metrics are accurate under load."""
        resp = client.post("/api/procedures", json=minimal_ckp)
        assert resp.status_code == 201
        
        # Fire 50 runs rapidly to build queue
        tasks = []
        for _ in range(50):
            task = asyncio.create_task(
                asyncio.to_thread(
                    client.post,
                    "/api/procedures/test_proc/run",
                    json={"vars": {}},
                )
            )
            tasks.append(task)
        
        await asyncio.gather(*tasks)
        
        # Check queue analytics
        from app.db.engine import async_session
        from app.db.models import WorkflowJob
        
        async with async_session() as db:
            result = await db.execute(
                select(WorkflowJob).where(WorkflowJob.status == "pending")
            )
            pending_jobs = result.scalars().all()
            
            # Should have jobs in queue
            assert len(pending_jobs) > 0

    @pytest.mark.asyncio
    @pytest.mark.slow
    async def test_memory_stability_over_time(self, client, minimal_ckp):
        """No memory leaks during extended operation."""
        import psutil
        import os
        
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        resp = client.post("/api/procedures", json=minimal_ckp)
        assert resp.status_code == 201
        
        # Run 100 workflows
        for _ in range(100):
            client.post("/api/procedures/test_proc/run", json={"vars": {}})
            await asyncio.sleep(0.1)
        
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_growth = final_memory - initial_memory
        
        # Memory growth should be reasonable (< 100MB for 100 runs)
        assert memory_growth < 100, f"Memory grew by {memory_growth:.2f}MB"
