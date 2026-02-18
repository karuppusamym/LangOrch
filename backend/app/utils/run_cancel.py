"""In-process run cancellation registry.

Each active execution registers an asyncio.Event keyed on ``run_id``.
When the /cancel endpoint is called, it sets the event so that the running
graph sees the signal at the next step boundary and stops cleanly.
"""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("langorch.run_cancel")

_events: dict[str, asyncio.Event] = {}


class RunCancelledError(Exception):
    """Raised inside execute_sequence when a cancellation signal is detected."""


def register(run_id: str) -> None:
    """Create a fresh (unset) cancellation event for *run_id*."""
    _events[run_id] = asyncio.Event()
    logger.debug("Cancel registry: registered run %s", run_id)


def mark_cancelled(run_id: str) -> None:
    """Signal cancellation for *run_id*. No-op if not registered."""
    event = _events.get(run_id)
    if event is not None:
        event.set()
        logger.info("Cancel registry: signalled run %s", run_id)
    else:
        logger.debug("Cancel registry: run %s not in registry (already finished?)", run_id)


def is_cancelled(run_id: str) -> bool:
    """Return True if a cancellation signal has been set for *run_id*."""
    event = _events.get(run_id)
    return event is not None and event.is_set()


def deregister(run_id: str) -> None:
    """Remove the event for *run_id* (call in finally block of execute_run)."""
    _events.pop(run_id, None)
    logger.debug("Cancel registry: deregistered run %s", run_id)
