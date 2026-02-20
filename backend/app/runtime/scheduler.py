"""Trigger scheduler — manages APScheduler jobs for `type: scheduled` triggers.

Runs as a background asyncio task. On each sync cycle it:
  1. Loads all enabled TriggerRegistrations with trigger_type="scheduled"
  2. Adds new APScheduler cron jobs for newly registered triggers
  3. Removes stale jobs whose registrations are gone or disabled
  4. Each job creates a Run via ``trigger_service.fire_trigger``
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger("langorch.scheduler")

_SYNC_INTERVAL = 30  # seconds


class TriggerScheduler:
    """Thin asyncio wrapper around APScheduler's AsyncIOScheduler."""

    def __init__(self) -> None:
        from apscheduler.schedulers.asyncio import AsyncIOScheduler  # type: ignore[import]
        self._scheduler = AsyncIOScheduler(timezone="UTC")
        self._running_jobs: dict[str, str] = {}  # job_id -> "<procedure_id>|<version>"
        self._sync_task: asyncio.Task[Any] | None = None

    # ── Lifecycle ───────────────────────────────────────────────

    def start(self) -> None:
        self._scheduler.start()
        self._sync_task = asyncio.create_task(self._sync_loop())
        logger.info("TriggerScheduler started")

    def stop(self) -> None:
        if self._sync_task:
            self._sync_task.cancel()
        self._scheduler.shutdown(wait=False)
        logger.info("TriggerScheduler stopped")

    # ── Sync loop ───────────────────────────────────────────────

    async def _sync_loop(self) -> None:
        while True:
            await asyncio.sleep(_SYNC_INTERVAL)
            try:
                await self.sync_schedules()
            except Exception:
                logger.exception("Error syncing trigger schedules")

    async def sync_schedules(self) -> None:
        """Reconcile APScheduler jobs with the DB trigger registrations."""
        from app.db.engine import async_session
        from app.services.trigger_service import list_trigger_registrations

        async with async_session() as db:
            registrations = await list_trigger_registrations(db, enabled_only=True)

        scheduled = [r for r in registrations if r.trigger_type == "scheduled" and r.schedule]
        active_keys = {f"{r.procedure_id}|{r.version}" for r in scheduled}

        # Remove stale jobs
        for job_id, key in list(self._running_jobs.items()):
            if key not in active_keys:
                try:
                    self._scheduler.remove_job(job_id)
                    logger.info("Removed stale cron job %s (%s)", job_id, key)
                except Exception:
                    pass
                del self._running_jobs[job_id]

        # Add new jobs
        existing_keys = set(self._running_jobs.values())
        for reg in scheduled:
            key = f"{reg.procedure_id}|{reg.version}"
            if key in existing_keys:
                continue
            try:
                job = self._scheduler.add_job(
                    _fire_scheduled_trigger,
                    trigger="cron",
                    **_parse_cron(reg.schedule),  # type: ignore[arg-type]
                    kwargs={"procedure_id": reg.procedure_id, "version": reg.version},
                    id=f"trigger_{reg.id}",
                    replace_existing=True,
                    misfire_grace_time=120,
                )
                self._running_jobs[job.id] = key
                logger.info(
                    "Registered cron job %s for %s v%s schedule=%s",
                    job.id, reg.procedure_id, reg.version, reg.schedule,
                )
            except Exception:
                logger.exception(
                    "Failed to register cron job for %s v%s schedule=%s",
                    reg.procedure_id, reg.version, reg.schedule,
                )


# ── Singleton ────────────────────────────────────────────────────

scheduler = TriggerScheduler()


# ── Helpers ──────────────────────────────────────────────────────


def _parse_cron(cron_expr: str) -> dict[str, str]:
    """Convert a cron expression string into APScheduler keyword arguments.

    Supports standard 5-field cron: ``minute hour day month day_of_week``.
    """
    parts = cron_expr.strip().split()
    if len(parts) == 5:
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }
    # Fallback — pass raw as 'minute' (will likely error, but at least surfaces the value)
    logger.warning("Unexpected cron expression format: %s", cron_expr)
    return {"minute": parts[0] if parts else "*"}


async def _fire_scheduled_trigger(procedure_id: str, version: str) -> None:
    """APScheduler job target — runs in asyncio event loop."""
    from app.db.engine import async_session
    from app.services.trigger_service import fire_trigger

    logger.info("Cron trigger firing for %s v%s", procedure_id, version)
    try:
        async with async_session() as db:
            run = await fire_trigger(
                db=db,
                procedure_id=procedure_id,
                version=version,
                trigger_type="scheduled",
                triggered_by="scheduler",
            )
            await db.commit()
            logger.info("Cron trigger created run %s for %s v%s", run.run_id, procedure_id, version)

        # Launch execution asynchronously
        asyncio.create_task(_execute_run(run.run_id, procedure_id, version))
    except Exception:
        logger.exception("Cron trigger failed for %s v%s", procedure_id, version)


async def _execute_run(run_id: str, procedure_id: str, version: str) -> None:
    """Start the execution pipeline for a trigger-fired run."""
    try:
        from app.db.engine import async_session
        from app.services.execution_service import execute_run

        await execute_run(run_id, async_session)
    except Exception:
        logger.exception("Execution failed for trigger run %s", run_id)
