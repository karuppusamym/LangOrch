"""Helpers for atomically enqueuing a RunJob when a run is created or resumed.

Two entry points:
  enqueue_run(db, run_id)  — synchronous add to session; for NEW runs where no
                              RunJob exists yet.  Caller commits once.
  requeue_run(db, run_id)  — async UPSERT; for approval-resume where a DONE
                              RunJob already exists for the same run_id.
                              Updates that row back to queued (re-uses the
                              unique-constrained run_id slot).  Falls back to
                              insert if no prior job exists.  Caller commits.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update

from app.config import settings
from app.db.models import RunJob


def _uuid() -> str:
    return uuid.uuid4().hex


def enqueue_run(
    db_session,
    run_id: str,
    *,
    priority: int = 0,
    max_attempts: int | None = None,
) -> RunJob:
    """Add a RunJob to *db_session* for *run_id*.

    The job is NOT committed here — the caller must ``await db.commit()``.
    This keeps the Run creation and RunJob creation in one atomic transaction.

    Args:
        db_session:  Active AsyncSession (or sync Session for tests).
        run_id:      The Run to execute.
        priority:    Higher = picked first by the worker (default 0).
                     Use priority=10 for approval-resume jobs.
        max_attempts: Override WORKER_MAX_ATTEMPTS for this specific job.
    """
    now = datetime.now(timezone.utc)
    job = RunJob(
        job_id=_uuid(),
        run_id=run_id,
        status="queued",
        priority=priority,
        attempts=0,
        max_attempts=max_attempts if max_attempts is not None else settings.WORKER_MAX_ATTEMPTS,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)
    return job


async def requeue_run(
    db_session,
    run_id: str,
    *,
    priority: int = 0,
    max_attempts: int | None = None,
) -> RunJob:
    """Re-enqueue a run that was previously executed (e.g. after an approval).

    Because ``run_jobs.run_id`` is UNIQUE, we cannot INSERT a second row for
    the same run.  This function:
      1. Looks for an existing RunJob for *run_id*.
      2. If found: resets it to ``queued`` in-place (UPDATE).
      3. If not found: falls back to a plain INSERT (same as ``enqueue_run``).

    The session is NOT committed here — the caller must ``await db.commit()``
    so that the approval decision and the RunJob update land atomically.
    """
    now = datetime.now(timezone.utc)
    _max_att = max_attempts if max_attempts is not None else settings.WORKER_MAX_ATTEMPTS

    result = await db_session.execute(
        select(RunJob).where(RunJob.run_id == run_id)
    )
    existing: RunJob | None = result.scalar_one_or_none()

    if existing is not None:
        # Reset the existing row so the worker will pick it up again.
        existing.status = "queued"
        existing.priority = priority
        existing.attempts = 0
        existing.max_attempts = _max_att
        existing.available_at = now
        existing.locked_by = None
        existing.locked_until = None
        existing.error_message = None
        existing.updated_at = now
        return existing

    # Fallback: no prior job — insert fresh (shouldn't normally happen for
    # a run that has already been executed, but handle it gracefully).
    job = RunJob(
        job_id=_uuid(),
        run_id=run_id,
        status="queued",
        priority=priority,
        attempts=0,
        max_attempts=_max_att,
        available_at=now,
        created_at=now,
        updated_at=now,
    )
    db_session.add(job)
    return job
