"""DB-level leader election for HA-safe singleton background tasks.

Multiple orchestrator replicas compete for the ``name='scheduler'`` row
in the ``scheduler_leader_leases`` table.  Only the current leader should
run APScheduler, the file-watch loop, and the approval-expiry loop.

Algorithm
---------
Every ``RENEW_INTERVAL`` seconds the background task tries three paths:

1. **Renew** — update our own existing row (we already hold the lease).
2. **Steal** — overwrite an expired row (previous leader died or restarted).
3. **Insert** — create the row from scratch (nobody has ever been leader).

``is_leader`` reflects the result of the last attempt.  All callers must
tolerate brief windows where ``is_leader`` transitions True → False
(e.g. during a DB hiccup) and resume gracefully once reclaimed.

SQLite (single process)
~~~~~~~~~~~~~~~~~~~~~~~
Always succeeds immediately on the INSERT path — the process is always
leader, matching the previous single-process behaviour exactly.

PostgreSQL (multi-replica)
~~~~~~~~~~~~~~~~~~~~~~~~~~
Concurrent INSERTs hit an ``IntegrityError`` on the primary-key conflict;
only one replica wins.  The others retry via the Steal path once the
lease expires.
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import uuid
from contextlib import suppress
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, update
from sqlalchemy.exc import IntegrityError

logger = logging.getLogger("langorch.leader")

_LEASE_TTL_SECONDS = 60   # lease lifetime before another replica can steal it
_RENEW_INTERVAL = 15      # how often the background task attempts renewal
_LEASE_NAME = "scheduler"


def _make_leader_id() -> str:
    """Unique identifier for this process instance (hostname-pid-rand)."""
    host = socket.gethostname()
    pid = os.getpid()
    rand = uuid.uuid4().hex[:8]
    return f"{host}-{pid}-{rand}"


class LeaderElection:
    """Manages a DB-backed leader lease for background singleton tasks.

    Usage::

        election = LeaderElection()
        election.start()          # begins background renewal
        ...
        if election.is_leader:
            do_singleton_work()
        ...
        election.stop()           # cancels renewal; lease expires naturally
    """

    def __init__(self, name: str = _LEASE_NAME) -> None:
        self._name = name
        self._leader_id: str = _make_leader_id()
        self._is_leader: bool = False
        self._task: asyncio.Task[Any] | None = None

    # ── Public API ────────────────────────────────────────────

    @property
    def is_leader(self) -> bool:
        """True when this process currently holds the leader lease."""
        return self._is_leader

    @property
    def leader_id(self) -> str:
        """Unique identifier for this process."""
        return self._leader_id

    def start(self) -> None:
        """Start the background renewal loop (idempotent)."""
        if self._task is not None and not self._task.done():
            return
        self._task = asyncio.create_task(self._loop(), name="leader-election")
        logger.info(
            "LeaderElection started: lease=%s id=%s ttl=%ds renew=%ds",
            self._name, self._leader_id, _LEASE_TTL_SECONDS, _RENEW_INTERVAL,
        )

    def stop(self) -> None:
        """Cancel the renewal loop.  The lease expires naturally after TTL."""
        if self._task:
            self._task.cancel()
            self._task = None
        self._is_leader = False
        logger.info("LeaderElection stopped: lease=%s id=%s", self._name, self._leader_id)

    # ── Background loop ───────────────────────────────────────

    async def _loop(self) -> None:
        while True:
            acquired = False
            try:
                acquired = await self._try_acquire_or_renew()
                if acquired and not self._is_leader:
                    logger.info(
                        "LeaderElection: became leader for lease=%s id=%s",
                        self._name, self._leader_id,
                    )
                elif not acquired and self._is_leader:
                    logger.warning(
                        "LeaderElection: lost leader lease=%s id=%s",
                        self._name, self._leader_id,
                    )
                self._is_leader = acquired
            except Exception:
                logger.exception(
                    "LeaderElection: unexpected error during acquire/renew (lease=%s)",
                    self._name,
                )
                self._is_leader = False

            # Always heartbeat our existence to the registry (standby or active)
            # even if the leader-lease acquisition failed — this keeps the worker
            # visible on the System Health page.
            try:
                await self._heartbeat_worker_registry(self._is_leader)
            except Exception:
                logger.exception(
                    "LeaderElection: failed to update worker registry (lease=%s id=%s)",
                    self._name, self._leader_id,
                )

            await asyncio.sleep(_RENEW_INTERVAL)

    # ── DB operations ─────────────────────────────────────────

    async def _heartbeat_worker_registry(self, is_leader: bool) -> None:
        """Upsert this instance's presence into the workers table."""
        from sqlalchemy.dialects.sqlite import insert as sqlite_insert
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        from app.db.engine import async_session
        from app.db.models import OrchestratorWorker

        now = datetime.now(timezone.utc)
        
        # We use a generic upsert since this table might be updated in PG or SQLite.
        # Often it's easier to just try UPDATE, if zero rows, try INSERT.
        # This keeps it database agnostic without pulling dialect specific inserts immediately.
        async with async_session() as db:
            if is_leader:
                # If we are the leader, actively demote all ghosts so there is only one true leader visible.
                await db.execute(
                    update(OrchestratorWorker)
                    .where(OrchestratorWorker.worker_id != self._leader_id)
                    .values(is_leader=False)
                )

            stmt = (
                update(OrchestratorWorker)
                .where(OrchestratorWorker.worker_id == self._leader_id)
                .values(is_leader=is_leader, last_heartbeat_at=now, status="online")
            )
            res = await db.execute(stmt)
            if res.rowcount == 0:
                try:
                    db.add(OrchestratorWorker(
                        worker_id=self._leader_id,
                        status="online",
                        is_leader=is_leader,
                        last_heartbeat_at=now,
                    ))
                    await db.commit()
                except IntegrityError:
                    await db.rollback()
            else:
                await db.commit()

    async def _try_acquire_or_renew(self) -> bool:
        from app.db.engine import async_session
        from app.db.models import SchedulerLeaderLease

        now = datetime.now(timezone.utc)
        expires = now + timedelta(seconds=_LEASE_TTL_SECONDS)

        async with async_session() as db:
            # Path 1: renew our own existing row
            stmt = (
                update(SchedulerLeaderLease)
                .where(
                    and_(
                        SchedulerLeaderLease.name == self._name,
                        SchedulerLeaderLease.leader_id == self._leader_id,
                    )
                )
                .values(acquired_at=now, expires_at=expires)
            )
            result = await db.execute(stmt)
            await db.commit()
            if result.rowcount == 1:
                logger.debug(
                    "LeaderElection: renewed lease=%s id=%s expires=%s",
                    self._name, self._leader_id, expires.isoformat(),
                )
                return True

            # Path 2: steal an expired lease
            stmt = (
                update(SchedulerLeaderLease)
                .where(
                    and_(
                        SchedulerLeaderLease.name == self._name,
                        SchedulerLeaderLease.expires_at < now,
                    )
                )
                .values(leader_id=self._leader_id, acquired_at=now, expires_at=expires)
            )
            result = await db.execute(stmt)
            await db.commit()
            if result.rowcount == 1:
                logger.info(
                    "LeaderElection: stole expired lease=%s new_leader=%s",
                    self._name, self._leader_id,
                )
                return True

            # Path 3: insert fresh row (first ever leader or table empty)
            try:
                db.add(
                    SchedulerLeaderLease(
                        name=self._name,
                        leader_id=self._leader_id,
                        acquired_at=now,
                        expires_at=expires,
                    )
                )
                await db.commit()
                logger.info(
                    "LeaderElection: acquired fresh lease=%s leader=%s",
                    self._name, self._leader_id,
                )
                return True
            except IntegrityError:
                # Another replica beat us to the INSERT
                await db.rollback()
                return False


# ── Singleton ────────────────────────────────────────────────────
#
# Imported by scheduler.py and main.py.  A single instance per process
# is sufficient — it covers all singleton background tasks on this host.

leader_election = LeaderElection()
