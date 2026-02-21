"""Run cancellation — in-process registry + DB-level signal.

Two-layer cancellation:

1. **In-process event** (``asyncio.Event``):
   - Fast, synchronous check at each step boundary inside ``node_executors.py``.
   - Only works within a single process.  Used by both embedded worker mode and
     the cancel API endpoint (single-process SQLite dev).

2. **DB-level flag** (``runs.cancellation_requested``):
   - Works across processes (separate API + worker).
   - The worker's heartbeat loop reads this flag and primes the in-process event
     so that ``is_cancelled()`` returns ``True`` inside a running execution.
   - The ``/cancel`` API endpoint sets this flag in addition to the in-process event.

Usage:
    # In API cancel endpoint (both signals):
    await mark_cancelled_db(run_id, db)
    mark_cancelled(run_id)          # in-process fast path

    # In worker heartbeat (bridging DB → in-process):
    if await is_cancelled_db(run_id, db):
        mark_cancelled(run_id)

    # In node_executors (fast synchronous check):
    if is_cancelled(run_id):
        raise RunCancelledError
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("langorch.run_cancel")

_events: dict[str, asyncio.Event] = {}


class RunCancelledError(Exception):
    """Raised inside execute_sequence when a cancellation signal is detected."""


# ─────────────────────────────────────────────────────────────────────────────
# In-process event registry
# ─────────────────────────────────────────────────────────────────────────────


def register(run_id: str) -> None:
    """Create a fresh (unset) cancellation event for *run_id*."""
    _events[run_id] = asyncio.Event()
    logger.debug("Cancel registry: registered run %s", run_id)


def mark_cancelled(run_id: str) -> None:
    """Signal cancellation for *run_id* in-process.  No-op if not registered."""
    event = _events.get(run_id)
    if event is not None:
        event.set()
        logger.info("Cancel registry: signalled run %s", run_id)
    else:
        logger.debug("Cancel registry: run %s not in registry (already finished?)", run_id)


def is_cancelled(run_id: str) -> bool:
    """Return True if an in-process cancellation signal has been set for *run_id*."""
    event = _events.get(run_id)
    return event is not None and event.is_set()


def deregister(run_id: str) -> None:
    """Remove the event for *run_id* (call in finally block of execute_run)."""
    _events.pop(run_id, None)
    logger.debug("Cancel registry: deregistered run %s", run_id)


# ─────────────────────────────────────────────────────────────────────────────
# DB-level signal (cross-process)
# ─────────────────────────────────────────────────────────────────────────────


async def mark_cancelled_db(run_id: str, db) -> bool:
    """Set ``cancellation_requested = True`` on the Run row.

    Returns True if the row was found and updated, False if not found.
    The caller is responsible for committing the session.
    """
    from sqlalchemy import update
    from app.db.models import Run

    result = await db.execute(
        update(Run)
        .where(Run.run_id == run_id)
        .values(cancellation_requested=True)
    )
    updated = result.rowcount > 0
    if updated:
        logger.info("Cancel DB: set cancellation_requested for run %s", run_id)
    else:
        logger.debug("Cancel DB: run %s not found", run_id)
    return updated


async def is_cancelled_db(run_id: str, db) -> bool:
    """Return True if ``cancellation_requested`` is set in the DB for *run_id*.

    Used by the worker heartbeat to bridge DB signal → in-process event.
    """
    from sqlalchemy import select
    from app.db.models import Run

    result = await db.execute(
        select(Run.cancellation_requested).where(Run.run_id == run_id)
    )
    row = result.first()
    return bool(row and row[0])


async def check_and_signal_cancellation(run_id: str, db) -> bool:
    """Check DB flag and prime the in-process event if set.

    Call from the worker heartbeat loop so that ``is_cancelled()`` becomes
    True inside the running execution on the next step boundary.
    Returns True if cancellation was signalled.
    """
    if await is_cancelled_db(run_id, db):
        mark_cancelled(run_id)
        return True
    return False

