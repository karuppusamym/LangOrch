"""Worker heartbeat — renews a job's ``locked_until`` while it is executing.

The heartbeat task runs as a sibling asyncio.Task alongside the execution
coroutine.  It does two things every ``interval`` seconds:

1. Renew ``locked_until = now() + lock_duration`` to prove the worker is
   still alive (prevents stalled-job reclaim from another worker).

2. Check the DB ``cancellation_requested`` flag and prime the in-process
   cancellation event if set (bridges the DB signal to the running execution).

Usage:
    task = asyncio.create_task(heartbeat_loop(job_id, run_id, interval=15, lock_duration=60))
    try:
        ...execute the run...
    finally:
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime, timedelta, timezone

logger = logging.getLogger("langorch.worker.heartbeat")


async def heartbeat_loop(
    job_id: str,
    run_id: str,
    interval: float,
    lock_duration: float,
) -> None:
    """Continuously renew *job_id*'s lock and bridge cancellation signals.

    This coroutine runs until it is cancelled (on job completion or failure).

    Args:
        job_id:        The RunJob primary key.
        run_id:        The associated Run ID (for cancellation check).
        interval:      Seconds between heartbeat ticks.
        lock_duration: New ``locked_until`` = now() + lock_duration (seconds).
    """
    from sqlalchemy import update, select
    from app.db.engine import async_session
    from app.db.models import RunJob
    from app.utils.run_cancel import check_and_signal_cancellation

    logger.debug("Heartbeat started for job %s (run %s)", job_id, run_id)

    while True:
        await asyncio.sleep(interval)
        try:
            now = datetime.now(timezone.utc)
            new_locked_until = now + timedelta(seconds=lock_duration)

            async with async_session() as db:
                # 1. Renew lock
                await db.execute(
                    update(RunJob)
                    .where(RunJob.job_id == job_id, RunJob.status == "running")
                    .values(locked_until=new_locked_until, updated_at=now)
                )
                await db.commit()
                logger.debug(
                    "Heartbeat renewed lock for job %s until %s", job_id, new_locked_until
                )

                # 2. Check for DB-level cancellation and signal in-process event
                async with async_session() as check_db:
                    cancelled = await check_and_signal_cancellation(run_id, check_db)
                    if cancelled:
                        logger.info(
                            "Heartbeat detected cancellation for run %s (job %s)",
                            run_id, job_id,
                        )

        except asyncio.CancelledError:
            logger.debug("Heartbeat cancelled for job %s", job_id)
            raise
        except Exception:
            logger.warning("Heartbeat error for job %s (will retry)", job_id, exc_info=True)
