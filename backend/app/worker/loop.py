"""Worker job poll-and-execute loop.

Architecture
------------
The loop polls ``run_jobs`` for eligible jobs, claims them atomically, then
executes each in a sibling asyncio.Task with a concurrent heartbeat task.

Claiming strategy (dialect-aware):
  PostgreSQL — ``SELECT … FOR UPDATE SKIP LOCKED`` in a single transaction.
               Correct under any number of concurrent workers.
  SQLite     — Optimistic UPDATE with a status guard (``WHERE status IN
               ('queued','retrying') AND job_id = ?``).  Race conditions are
               impossible in single-process embedded mode; the pattern also
               works correctly if two separate SQLite workers somehow exist.

Job lifecycle:
  queued / retrying
    ↓   poll_and_claim()
  running  ← heartbeat renews locked_until every WORKER_HEARTBEAT_INTERVAL s
    ↓   execute_job()
  done     (on success)
  failed   (on final failure — attempts >= max_attempts)
  retrying (on retriable failure — re-enqueued with available_at delay)

Stalled jobs:
  reclaim_stalled_jobs() finds ``status=running AND locked_until < now()``
  and resets them to ``queued`` (or ``failed`` if max_attempts exceeded).
  Called at the start of every poll cycle.
"""

from __future__ import annotations

import asyncio
import logging
import socket
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update, text

from app.config import settings
from app.db.engine import async_session
from app.db.models import Run, RunJob

logger = logging.getLogger("langorch.worker.loop")


def _default_worker_id() -> str:
    return f"{socket.gethostname()}-{uuid.uuid4().hex[:8]}"


# ─────────────────────────────────────────────────────────────────────────────
# Claim helpers
# ─────────────────────────────────────────────────────────────────────────────


async def _claim_jobs_postgres(
    worker_id: str,
    slots: int,
) -> list[RunJob]:
    """Claim up to *slots* jobs using FOR UPDATE SKIP LOCKED (PostgreSQL)."""
    now = datetime.now(timezone.utc)
    locked_until = now + timedelta(seconds=settings.WORKER_LOCK_DURATION_SECONDS)

    async with async_session() as db:
        async with db.begin():
            result = await db.execute(
                text(
                    """
                    SELECT job_id FROM run_jobs
                    WHERE status IN ('queued', 'retrying')
                      AND available_at <= :now
                    ORDER BY priority DESC, available_at ASC
                    LIMIT :limit
                    FOR UPDATE SKIP LOCKED
                    """
                ),
                {"now": now, "limit": slots},
            )
            job_ids = [row[0] for row in result.fetchall()]
            if not job_ids:
                return []

            # Claim all in one UPDATE
            await db.execute(
                text(
                    """
                    UPDATE run_jobs
                    SET status      = 'running',
                        locked_by   = :worker_id,
                        locked_until = :locked_until,
                        attempts    = attempts + 1,
                        updated_at  = :now
                    WHERE job_id = ANY(:job_ids)
                    """
                ),
                {
                    "worker_id": worker_id,
                    "locked_until": locked_until,
                    "now": now,
                    "job_ids": job_ids,
                },
            )

        # Reload the claimed jobs to get full objects
        result2 = await db.execute(
            select(RunJob).where(RunJob.job_id.in_(job_ids))
        )
        return list(result2.scalars().all())


async def _claim_jobs_sqlite(
    worker_id: str,
    slots: int,
) -> list[RunJob]:
    """Claim up to *slots* jobs using optimistic locking (SQLite / dev)."""
    now = datetime.now(timezone.utc)
    locked_until = now + timedelta(seconds=settings.WORKER_LOCK_DURATION_SECONDS)
    claimed: list[RunJob] = []

    async with async_session() as db:
        # Find candidates
        result = await db.execute(
            select(RunJob)
            .where(
                RunJob.status.in_(["queued", "retrying"]),
                RunJob.available_at <= now,
            )
            .order_by(RunJob.priority.desc(), RunJob.available_at.asc())
            .limit(slots)
        )
        candidates = list(result.scalars().all())

        for job in candidates:
            # Optimistic claim: only update if status hasn't changed
            update_result = await db.execute(
                update(RunJob)
                .where(
                    RunJob.job_id == job.job_id,
                    RunJob.status.in_(["queued", "retrying"]),
                )
                .values(
                    status="running",
                    locked_by=worker_id,
                    locked_until=locked_until,
                    attempts=RunJob.attempts + 1,
                    updated_at=now,
                )
            )
            if update_result.rowcount == 1:
                job.status = "running"
                job.locked_by = worker_id
                job.locked_until = locked_until
                job.attempts = (job.attempts or 0) + 1
                claimed.append(job)

        await db.commit()

    return claimed


async def poll_and_claim(worker_id: str, slots: int) -> list[RunJob]:
    """Return up to *slots* claimed RunJob objects ready for execution."""
    if slots <= 0:
        return []
    if settings.is_postgres:
        return await _claim_jobs_postgres(worker_id, slots)
    return await _claim_jobs_sqlite(worker_id, slots)


# ─────────────────────────────────────────────────────────────────────────────
# Stalled-job recovery
# ─────────────────────────────────────────────────────────────────────────────


async def reclaim_stalled_jobs() -> int:
    """Reset stalled jobs (lock expired while still running) back to queued.

    Jobs that have exceeded max_attempts are marked ``failed`` instead.
    Returns the number of jobs reclaimed.
    """
    now = datetime.now(timezone.utc)
    reclaimed = 0

    async with async_session() as db:
        result = await db.execute(
            select(RunJob).where(
                RunJob.status == "running",
                RunJob.locked_until < now,
            )
        )
        stalled = list(result.scalars().all())

        for job in stalled:
            if (job.attempts or 0) >= (job.max_attempts or settings.WORKER_MAX_ATTEMPTS):
                job.status = "failed"
                job.error_message = "Exceeded max_attempts — last lock expired without completion"
                logger.warning(
                    "Job %s (run %s) permanently failed: max attempts exceeded",
                    job.job_id, job.run_id,
                )
            else:
                retry_delay = settings.WORKER_RETRY_DELAY_SECONDS * (job.attempts or 1)
                job.status = "retrying"
                job.locked_by = None
                job.locked_until = None
                job.available_at = now + timedelta(seconds=retry_delay)
                logger.info(
                    "Reclaimed stalled job %s (run %s, attempt %d) — retry in %.0fs",
                    job.job_id, job.run_id, job.attempts, retry_delay,
                )
            job.updated_at = now
            reclaimed += 1

        if reclaimed:
            await db.commit()

    return reclaimed


# ─────────────────────────────────────────────────────────────────────────────
# Job execution
# ─────────────────────────────────────────────────────────────────────────────


async def execute_job(job: RunJob, worker_id: str) -> None:
    """Execute a single claimed RunJob — called from the worker loop.

    Wraps ``execution_service.execute_run()`` with:
    - Heartbeat task (renews lock, bridges DB cancel → in-process event)
    - Success: marks job ``done``
    - Failure: marks job ``retrying`` (if attempts < max_attempts) or ``failed``
    - Pre-execution cancel guard: load run, check ``cancellation_requested``
    """
    from app.services.execution_service import execute_run
    from app.utils.run_cancel import mark_cancelled, check_and_signal_cancellation
    from app.worker.heartbeat import heartbeat_loop

    now = datetime.now(timezone.utc)

    # --- Pre-execution cancel guard ---
    async with async_session() as db:
        cancelled = await check_and_signal_cancellation(job.run_id, db)
        if cancelled:
            logger.info(
                "Job %s (run %s) cancelled before execution started — skipping",
                job.job_id, job.run_id,
            )
            await db.execute(
                update(RunJob)
                .where(RunJob.job_id == job.job_id)
                .values(status="cancelled", locked_by=None, updated_at=now)
            )
            await db.commit()
            return

    # --- Start heartbeat task ---
    heartbeat_task = asyncio.create_task(
        heartbeat_loop(
            job_id=job.job_id,
            run_id=job.run_id,
            interval=settings.WORKER_HEARTBEAT_INTERVAL,
            lock_duration=settings.WORKER_LOCK_DURATION_SECONDS,
        )
    )

    try:
        logger.info(
            "Worker %s executing job %s (run %s, attempt %d/%d)",
            worker_id, job.job_id, job.run_id,
            job.attempts, job.max_attempts or settings.WORKER_MAX_ATTEMPTS,
        )
        await execute_run(job.run_id, async_session)

        # Mark done
        now = datetime.now(timezone.utc)
        async with async_session() as db:
            await db.execute(
                update(RunJob)
                .where(RunJob.job_id == job.job_id)
                .values(
                    status="done",
                    locked_by=None,
                    locked_until=None,
                    updated_at=now,
                )
            )
            await db.commit()
        # Mirror onto in-memory object (useful for callers and tests)
        job.status = "done"
        job.locked_by = None
        job.locked_until = None

        logger.info("Job %s (run %s) completed successfully", job.job_id, job.run_id)

    except Exception as exc:
        now = datetime.now(timezone.utc)
        attempts = job.attempts or 0
        max_att = job.max_attempts or settings.WORKER_MAX_ATTEMPTS

        if attempts < max_att:
            retry_delay = settings.WORKER_RETRY_DELAY_SECONDS * attempts
            new_status = "retrying"
            new_available = now + timedelta(seconds=retry_delay)
            logger.warning(
                "Job %s (run %s) failed (attempt %d/%d) — retrying in %.0fs: %s",
                job.job_id, job.run_id, attempts, max_att, retry_delay, exc,
            )
        else:
            new_status = "failed"
            new_available = now
            logger.error(
                "Job %s (run %s) permanently failed after %d attempts: %s",
                job.job_id, job.run_id, attempts, exc,
            )

        async with async_session() as db:
            await db.execute(
                update(RunJob)
                .where(RunJob.job_id == job.job_id)
                .values(
                    status=new_status,
                    locked_by=None,
                    locked_until=None,
                    available_at=new_available,
                    error_message=str(exc)[:2000],
                    updated_at=now,
                )
            )
            await db.commit()
        # Mirror onto in-memory object (useful for callers and tests)
        job.status = new_status
        job.locked_by = None
        job.locked_until = None
        job.error_message = str(exc)[:2000]

    finally:
        heartbeat_task.cancel()
        with suppress(asyncio.CancelledError):
            await heartbeat_task


# ─────────────────────────────────────────────────────────────────────────────
# Main worker loop
# ─────────────────────────────────────────────────────────────────────────────


async def worker_loop(
    worker_id: str | None = None,
    concurrency: int | None = None,
    poll_interval: float | None = None,
) -> None:
    """Continuously poll for jobs and execute them up to *concurrency* at once.

    This coroutine runs until it is cancelled (e.g. on server shutdown).

    Args:
        worker_id:     Unique identifier for this worker (default: hostname+uuid).
        concurrency:   Max simultaneous executions (default: WORKER_CONCURRENCY).
        poll_interval: Seconds between poll cycles (default: WORKER_POLL_INTERVAL).
    """
    _worker_id = worker_id or _default_worker_id()
    _concurrency = concurrency if concurrency is not None else settings.WORKER_CONCURRENCY
    _poll_interval = poll_interval if poll_interval is not None else settings.WORKER_POLL_INTERVAL

    logger.info(
        "Worker %s started (concurrency=%d, poll_interval=%.1fs, dialect=%s)",
        _worker_id, _concurrency, _poll_interval, settings.ORCH_DB_DIALECT,
    )

    active_tasks: set[asyncio.Task] = set()

    while True:
        try:
            # Remove completed tasks
            done = {t for t in active_tasks if t.done()}
            for task in done:
                with suppress(Exception):
                    await task  # surface exceptions to log
            active_tasks -= done

            # Recover stalled jobs from any previous worker crash
            try:
                stalled = await reclaim_stalled_jobs()
                if stalled:
                    logger.debug("Reclaimed %d stalled job(s)", stalled)
            except Exception:
                logger.exception("Error in stalled-job reclaim")

            # Claim available slots
            available_slots = _concurrency - len(active_tasks)
            if available_slots > 0:
                try:
                    jobs = await poll_and_claim(_worker_id, available_slots)
                    for job in jobs:
                        task = asyncio.create_task(
                            execute_job(job, _worker_id),
                            name=f"job-{job.job_id}",
                        )
                        active_tasks.add(task)
                except Exception:
                    logger.exception("Error claiming jobs")

        except asyncio.CancelledError:
            logger.info("Worker %s shutting down (%d active tasks)…", _worker_id, len(active_tasks))
            # Cancel all active tasks and wait for them
            for task in active_tasks:
                task.cancel()
            if active_tasks:
                await asyncio.gather(*active_tasks, return_exceptions=True)
            raise

        except Exception:
            logger.exception("Unexpected error in worker loop; will retry")

        await asyncio.sleep(_poll_interval)
