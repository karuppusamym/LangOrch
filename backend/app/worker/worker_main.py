"""Worker process entrypoint.

Run as a standalone process (production PostgreSQL mode):

    # From backend/ directory:
    python -m app.worker

    # With custom worker ID:
    WORKER_ID=worker-1 python -m app.worker

    # With custom concurrency:
    WORKER_CONCURRENCY=8 python -m app.worker

The worker will:
1. Load app.config.settings (honours .env file)
2. Block until tables exist (new Alembic deployments may have a brief gap)
3. Start the poll-and-execute loop
4. Handle SIGINT/SIGTERM gracefully (drain active jobs, then exit)

For single-process dev mode (SQLite), the worker is started automatically
as an asyncio.Task inside the API process (WORKER_EMBEDDED=true default).
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal

logger = logging.getLogger("langorch.worker")


async def _wait_for_db(max_retries: int = 10, delay: float = 2.0) -> None:
    """Wait until the ``run_jobs`` table is accessible."""
    from sqlalchemy import text
    from app.db.engine import async_session

    for attempt in range(1, max_retries + 1):
        try:
            async with async_session() as db:
                await db.execute(text("SELECT 1 FROM run_jobs LIMIT 1"))
            logger.info("Database ready after %d attempt(s)", attempt)
            return
        except Exception as exc:
            logger.warning(
                "Database not ready (attempt %d/%d): %s", attempt, max_retries, exc
            )
            if attempt < max_retries:
                await asyncio.sleep(delay)

    raise RuntimeError(
        f"Database not accessible after {max_retries} attempts. "
        "Run `alembic upgrade head` before starting the worker."
    )


async def main() -> None:
    """Worker process entrypoint."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )

    from app.config import settings
    from app.worker.loop import worker_loop

    worker_id = os.environ.get("WORKER_ID")
    concurrency = settings.WORKER_CONCURRENCY
    poll_interval = settings.WORKER_POLL_INTERVAL

    logger.info(
        "Starting LangOrch worker (dialect=%s, embedded=%s)",
        settings.ORCH_DB_DIALECT,
        settings.WORKER_EMBEDDED,
    )

    await _wait_for_db()

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()

    def _handle_stop(*_):
        logger.info("Received shutdown signal — stopping worker")
        stop_event.set()

    # Register SIGINT/SIGTERM handlers (Unix only; Windows uses default)
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _handle_stop)
        except (NotImplementedError, AttributeError):
            # Windows doesn't support add_signal_handler
            pass

    worker_task = asyncio.create_task(
        worker_loop(
            worker_id=worker_id,
            concurrency=concurrency,
            poll_interval=poll_interval,
        )
    )

    # Run until stop signal
    await stop_event.wait()
    worker_task.cancel()
    try:
        await worker_task
    except asyncio.CancelledError:
        pass

    logger.info("Worker stopped cleanly")


if __name__ == "__main__":
    asyncio.run(main())
