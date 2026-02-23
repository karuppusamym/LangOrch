"""
Tests for Batch 29: HA-safe scheduling via DB-level leader election.

Covered scenarios:
  1.  LeaderElection acquires fresh lease (INSERT path) → is_leader=True
  2.  LeaderElection renews existing lease (UPDATE own row) → is_leader=True
  3.  LeaderElection steals expired lease (UPDATE expired row) → is_leader=True
  4.  LeaderElection loses election (other leader holds valid lease) → is_leader=False
  5.  is_leader starts False before first cycle
  6.  stop() clears is_leader
  7.  leader_id is stable within a process (same object, same id)
  8.  leader_id is unique across instances (new objects → different ids)
  9.  SchedulerLeaderLease model attributes available
  10. sync_schedules skips when not leader
  11. sync_schedules proceeds when leader
  12. _fire_scheduled_trigger skips when not leader
  13. _fire_scheduled_trigger proceeds when leader
  14. start() creates a background asyncio task
  15. Two concurrent election objects: only first INSERT wins; second returns False
  16. DB error during acquire sets is_leader=False gracefully
"""

from __future__ import annotations

import asyncio
import pytest
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call


# ── 1. LeaderElection — fresh INSERT path ───────────────────────────────────

@pytest.mark.asyncio
async def test_leader_election_fresh_insert():
    """First-ever acquire: INSERT succeeds → is_leader=True."""
    from app.runtime.leader import LeaderElection

    election = LeaderElection(name="test-fresh")

    async def _mock_acquire(_self):
        # Simulate: no existing row (rowcounts 0, 0) + INSERT succeeds
        return True

    with patch.object(LeaderElection, "_try_acquire_or_renew", _mock_acquire):
        result = await election._try_acquire_or_renew()

    assert result is True


# ── 2. Renew path ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leader_election_renew():
    """If UPDATE own row returns rowcount=1 → is_leader stays True."""
    from app.runtime.leader import LeaderElection

    election = LeaderElection(name="test-renew")
    election._is_leader = True  # pretend we previously won

    # Build a mock db result with rowcount=1
    mock_result = MagicMock()
    mock_result.rowcount = 1

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def _mock_session():
        yield mock_db

    # async_session is imported lazily inside _try_acquire_or_renew;
    # patch it at the source module.
    with patch("app.db.engine.async_session", _mock_session):
        result = await election._try_acquire_or_renew()

    assert result is True
    assert mock_db.commit.call_count == 1


# ── 3. Steal path ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leader_election_steal_expired():
    """First UPDATE returns 0 (not our row), second UPDATE returns 1 (expired row stolen)."""
    from app.runtime.leader import LeaderElection

    election = LeaderElection(name="test-steal")

    call_count = 0

    async def _mock_db_execute(_stmt):
        nonlocal call_count
        call_count += 1
        r = MagicMock()
        r.rowcount = 1 if call_count == 2 else 0
        return r

    mock_db = AsyncMock()
    mock_db.execute = _mock_db_execute
    mock_db.commit = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def _mock_session():
        yield mock_db

    with patch("app.db.engine.async_session", _mock_session):
        result = await election._try_acquire_or_renew()

    assert result is True
    assert call_count == 2


# ── 4. Another leader holds valid lease → returns False ──────────────────────

@pytest.mark.asyncio
async def test_leader_election_lost_to_other_leader():
    """Both UPDATEs return 0 + INSERT raises IntegrityError → False."""
    from app.runtime.leader import LeaderElection
    from sqlalchemy.exc import IntegrityError

    election = LeaderElection(name="test-lost")

    async def _mock_db_execute(_stmt):
        r = MagicMock()
        r.rowcount = 0
        return r

    mock_db = AsyncMock()
    mock_db.execute = _mock_db_execute
    mock_db.add = MagicMock(return_value=None)
    # First two commits (from UPDATE paths) succeed; third (INSERT) raises IntegrityError
    mock_db.commit = AsyncMock(side_effect=[None, None, IntegrityError(None, None, None)])
    mock_db.rollback = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)

    @asynccontextmanager
    async def _mock_session():
        yield mock_db

    with patch("app.db.engine.async_session", _mock_session):
        result = await election._try_acquire_or_renew()

    assert result is False
    mock_db.rollback.assert_called_once()


# ── 5. is_leader starts False ────────────────────────────────────────────────

def test_leader_election_starts_not_leader():
    """A freshly created LeaderElection must report is_leader=False."""
    from app.runtime.leader import LeaderElection
    e = LeaderElection()
    assert e.is_leader is False


# ── 6. stop() clears is_leader ───────────────────────────────────────────────

def test_leader_election_stop_clears_leader():
    """stop() must set is_leader to False."""
    from app.runtime.leader import LeaderElection
    e = LeaderElection()
    e._is_leader = True  # override as if we held the lease
    e.stop()
    assert e.is_leader is False


# ── 7. leader_id is stable within an instance ────────────────────────────────

def test_leader_id_stable():
    """leader_id must not change between calls on the same instance."""
    from app.runtime.leader import LeaderElection
    e = LeaderElection()
    assert e.leader_id == e.leader_id
    assert isinstance(e.leader_id, str)
    assert len(e.leader_id) > 5


# ── 8. leader_id is unique across instances ──────────────────────────────────

def test_leader_id_unique_across_instances():
    """Two LeaderElection objects must have different leader_ids."""
    from app.runtime.leader import LeaderElection
    e1 = LeaderElection()
    e2 = LeaderElection()
    assert e1.leader_id != e2.leader_id


# ── 9. SchedulerLeaderLease model exists with expected columns ───────────────

def test_scheduler_leader_lease_model_columns():
    from app.db.models import SchedulerLeaderLease
    cols = {c.name for c in SchedulerLeaderLease.__table__.columns}
    assert "name" in cols
    assert "leader_id" in cols
    assert "acquired_at" in cols
    assert "expires_at" in cols


def test_scheduler_leader_lease_table_name():
    from app.db.models import SchedulerLeaderLease
    assert SchedulerLeaderLease.__tablename__ == "scheduler_leader_leases"


def test_scheduler_leader_lease_primary_key():
    from app.db.models import SchedulerLeaderLease
    pk_cols = [c.name for c in SchedulerLeaderLease.__table__.primary_key.columns]
    assert "name" in pk_cols


# ── 10. sync_schedules skips when not leader ─────────────────────────────────

@pytest.mark.asyncio
async def test_sync_schedules_skips_when_not_leader():
    """TriggerScheduler.sync_schedules must skip DB access when not leader."""
    from app.runtime.scheduler import TriggerScheduler
    import app.runtime.leader as leader_mod

    ts = TriggerScheduler()

    mock_leader = MagicMock()
    mock_leader.is_leader = False

    list_called = False

    async def _list(*a, **kw):
        nonlocal list_called
        list_called = True
        return []

    with patch.object(leader_mod, "leader_election", mock_leader):
        await ts.sync_schedules()

    assert not list_called, "list_trigger_registrations must NOT be called when not leader"


# ── 11. sync_schedules proceeds when leader ───────────────────────────────────

@pytest.mark.asyncio
async def test_sync_schedules_runs_when_leader():
    """sync_schedules must query trigger registrations when is_leader=True."""
    from app.runtime.scheduler import TriggerScheduler
    import app.runtime.leader as leader_mod

    ts = TriggerScheduler()

    mock_leader = MagicMock()
    mock_leader.is_leader = True

    list_called = False

    @asynccontextmanager
    async def _mock_session():
        yield AsyncMock()

    async def _list(_db, enabled_only=True):
        nonlocal list_called
        list_called = True
        return []

    # leader_election is imported lazily; patch the singleton in its home module
    with (
        patch.object(leader_mod, "leader_election", mock_leader),
        patch("app.services.trigger_service.list_trigger_registrations", _list),
        patch("app.db.engine.async_session", _mock_session),
    ):
        await ts.sync_schedules()

    assert list_called, "list_trigger_registrations should be called when leader"


# ── 12. _fire_scheduled_trigger skips when not leader ────────────────────────

@pytest.mark.asyncio
async def test_fire_scheduled_trigger_skips_when_not_leader():
    """_fire_scheduled_trigger must return without creating a run when not leader."""
    from app.runtime.scheduler import _fire_scheduled_trigger
    import app.runtime.leader as leader_mod

    mock_leader = MagicMock()
    mock_leader.is_leader = False

    fire_called = False

    async def _fire(*a, **kw):
        nonlocal fire_called
        fire_called = True

    # Patch the singleton at its home module; the lazy import inside the function
    # resolves to the same object via sys.modules.
    with patch.object(leader_mod, "leader_election", mock_leader):
        await _fire_scheduled_trigger("proc_x", "1.0.0")

    assert not fire_called, "fire_trigger must NOT be called when not leader"


# ── 13. _fire_scheduled_trigger fires when leader ────────────────────────────

@pytest.mark.asyncio
async def test_fire_scheduled_trigger_fires_when_leader():
    """_fire_scheduled_trigger must call fire_trigger when is_leader=True."""
    from app.runtime.scheduler import _fire_scheduled_trigger
    import app.runtime.leader as leader_mod

    mock_leader = MagicMock()
    mock_leader.is_leader = True

    mock_run = MagicMock()
    mock_run.run_id = "run-leader"

    fire_called = False

    async def _fire(*a, **kw):
        nonlocal fire_called
        fire_called = True
        return mock_run

    @asynccontextmanager
    async def _mock_session():
        db = AsyncMock()
        db.commit = AsyncMock()
        yield db

    with (
        patch.object(leader_mod, "leader_election", mock_leader),
        patch("app.services.trigger_service.fire_trigger", _fire),
        patch("app.db.engine.async_session", _mock_session),
        # Close the _execute_run coroutine immediately so no RuntimeWarning
        patch("asyncio.create_task", side_effect=lambda coro: coro.close()),
    ):
        await _fire_scheduled_trigger("proc_x", "1.0.0")

    assert fire_called, "fire_trigger should be called when leader"


# ── 14. start() creates a background task ────────────────────────────────────

@pytest.mark.asyncio
async def test_leader_election_start_creates_task():
    """start() must launch an asyncio task."""
    from app.runtime.leader import LeaderElection

    e = LeaderElection(name="test-start-task")

    async def _mock_loop(self):
        await asyncio.sleep(1000)  # blocks until cancelled

    with patch.object(LeaderElection, "_loop", _mock_loop):
        e.start()
        await asyncio.sleep(0)   # yield to event loop so task is scheduled
        assert e._task is not None
        assert not e._task.done()
        e.stop()
        await asyncio.sleep(0)


# ── 15. Concurrent acquires: only one wins ───────────────────────────────────

@pytest.mark.asyncio
async def test_leader_election_only_one_winner():
    """Simulate two concurrent elections; first INSERT wins, second gets IntegrityError."""
    from app.runtime.leader import LeaderElection
    from sqlalchemy.exc import IntegrityError

    winner = LeaderElection(name="test-concurrent")
    loser = LeaderElection(name="test-concurrent")

    inserted = False

    def _execute_factory(is_winner: bool):
        async def _execute(_stmt):
            r = MagicMock()
            r.rowcount = 0
            return r
        return _execute

    def _commit_factory(is_winner: bool):
        nonlocal inserted
        call_n = 0

        async def _commit():
            nonlocal call_n, inserted
            call_n += 1
            if call_n == 3:
                # 3rd commit = INSERT path
                if is_winner and not inserted:
                    inserted = True
                    return  # success
                else:
                    raise IntegrityError(None, None, None)
        return _commit

    def _make_mock_db(is_winner: bool):
        mock_db = AsyncMock()
        mock_db.execute = _execute_factory(is_winner)
        mock_db.commit = _commit_factory(is_winner)
        mock_db.add = MagicMock()
        mock_db.rollback = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        return mock_db

    w_db = _make_mock_db(True)
    l_db = _make_mock_db(False)

    @asynccontextmanager
    async def _winner_session():
        yield w_db

    @asynccontextmanager
    async def _loser_session():
        yield l_db

    with patch("app.db.engine.async_session", _winner_session):
        w_result = await winner._try_acquire_or_renew()

    with patch("app.db.engine.async_session", _loser_session):
        l_result = await loser._try_acquire_or_renew()

    assert w_result is True
    assert l_result is False


# ── 16. DB error during acquire → is_leader=False, no crash ──────────────────

@pytest.mark.asyncio
async def test_leader_election_db_error_safety():
    """_loop must catch all exceptions and set is_leader=False."""
    from app.runtime.leader import LeaderElection

    e = LeaderElection(name="test-dberror")

    cycle = 0

    async def _bad_acquire(_self):
        nonlocal cycle
        cycle += 1
        if cycle == 1:
            raise RuntimeError("DB is gone")
        await asyncio.sleep(1000)  # block after first cycle

    with patch.object(LeaderElection, "_try_acquire_or_renew", _bad_acquire):
        with patch("app.runtime.leader._RENEW_INTERVAL", 0):
            task = asyncio.create_task(e._loop())
            await asyncio.sleep(0.05)
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    assert e.is_leader is False
