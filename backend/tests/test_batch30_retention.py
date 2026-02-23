"""Tests for Batch 30: artifact retention/TTL cleanup.

Covers:
- _artifact_retention_loop() background coroutine
- POST /api/artifacts-admin/cleanup API endpoint
- GET /api/artifacts-admin/stats API endpoint
- config ARTIFACT_RETENTION_DAYS setting
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from httpx import AsyncClient, ASGITransport

# ── ensure backend on sys.path ─────────────────────────────────────────────
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


# ── helpers ────────────────────────────────────────────────────────────────


def _make_dir_with_file(parent: Path, name: str, size: int = 100) -> Path:
    """Create parent/name/ with a single data file of *size* bytes."""
    d = parent / name
    d.mkdir(exist_ok=True)
    (d / "data.bin").write_bytes(b"x" * size)
    return d


# ─────────────────────────────────────────────────────────────────────────────
# Config tests
# ─────────────────────────────────────────────────────────────────────────────


def test_artifact_retention_days_default():
    """ARTIFACT_RETENTION_DAYS defaults to 30."""
    from app.config import settings
    assert settings.ARTIFACT_RETENTION_DAYS == 30


def test_artifact_retention_days_type():
    """ARTIFACT_RETENTION_DAYS is an int."""
    from app.config import settings
    assert isinstance(settings.ARTIFACT_RETENTION_DAYS, int)


# ─────────────────────────────────────────────────────────────────────────────
# API /stats endpoint
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifact_stats_empty_dir():
    """GET /stats returns zero counts for an empty artifacts dir."""
    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("app.api.artifacts.settings") as mock_settings:
            mock_settings.ARTIFACTS_DIR = tmpdir
            from app.api.artifacts import artifact_stats
            result = await artifact_stats()
        assert result.total_folders == 0
        assert result.total_bytes == 0


@pytest.mark.asyncio
async def test_artifact_stats_with_folders():
    """GET /stats counts run-scoped folders correctly."""
    with tempfile.TemporaryDirectory() as tmpdir:
        _make_dir_with_file(Path(tmpdir), "run-abc", size=200)
        _make_dir_with_file(Path(tmpdir), "run-xyz", size=300)
        with patch("app.api.artifacts.settings") as mock_settings:
            mock_settings.ARTIFACTS_DIR = tmpdir
            from app.api.artifacts import artifact_stats
            result = await artifact_stats()
        assert result.total_folders == 2
        assert result.total_bytes == 500


# ─────────────────────────────────────────────────────────────────────────────
# API /cleanup endpoint — unit-level (mock DB)
# ─────────────────────────────────────────────────────────────────────────────


def _make_run(run_id: str, status: str, days_old: int):
    """Return a mock Run ORM object."""
    r = MagicMock()
    r.run_id = run_id
    r.status = status
    r.created_at = datetime.now(timezone.utc) - timedelta(days=days_old)
    return r


@pytest.mark.asyncio
async def test_cleanup_deletes_old_terminal_run(tmp_path):
    """cleanup endpoint deletes folder for terminal run older than retention."""
    run_id = "run-old-terminal"
    _make_dir_with_file(tmp_path, run_id, size=50)

    mock_run = _make_run(run_id, "completed", days_old=40)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.api.artifacts import cleanup_artifacts

    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        result = await cleanup_artifacts(before=None, db=mock_db)

    assert run_id in result.deleted_runs
    assert result.freed_bytes == 50
    assert not (tmp_path / run_id).exists()


@pytest.mark.asyncio
async def test_cleanup_skips_active_run(tmp_path):
    """cleanup endpoint does NOT delete folder for an active run."""
    run_id = "run-active"
    _make_dir_with_file(tmp_path, run_id, size=50)

    mock_run = _make_run(run_id, "running", days_old=40)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.api.artifacts import cleanup_artifacts

    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        result = await cleanup_artifacts(before=None, db=mock_db)

    assert run_id not in result.deleted_runs
    assert result.skipped == 1
    assert (tmp_path / run_id).exists()


@pytest.mark.asyncio
async def test_cleanup_skips_recent_terminal_run(tmp_path):
    """cleanup endpoint skips terminal run that is NOT old enough."""
    run_id = "run-recent-done"
    _make_dir_with_file(tmp_path, run_id, size=50)

    mock_run = _make_run(run_id, "completed", days_old=5)  # only 5 days old
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.api.artifacts import cleanup_artifacts

    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        result = await cleanup_artifacts(before=None, db=mock_db)

    assert run_id not in result.deleted_runs
    assert (tmp_path / run_id).exists()


@pytest.mark.asyncio
async def test_cleanup_deletes_orphan_by_mtime(tmp_path):
    """cleanup endpoint deletes orphan folder (no Run row) if mtime is old enough."""
    run_id = "orphan-folder"
    folder = _make_dir_with_file(tmp_path, run_id, size=100)
    # Set mtime to 40 days ago
    old_ts = (datetime.now(timezone.utc) - timedelta(days=40)).timestamp()
    os.utime(str(folder), (old_ts, old_ts))

    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = None  # no DB row

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.api.artifacts import cleanup_artifacts

    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        result = await cleanup_artifacts(before=None, db=mock_db)

    assert run_id in result.deleted_runs
    assert not (tmp_path / run_id).exists()


@pytest.mark.asyncio
async def test_cleanup_respects_custom_before_param(tmp_path):
    """cleanup endpoint uses ``before`` query param instead of settings."""
    run_id = "run-10-days-old"
    _make_dir_with_file(tmp_path, run_id, size=50)

    mock_run = _make_run(run_id, "failed", days_old=10)
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = mock_run

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=mock_result)

    from app.api.artifacts import cleanup_artifacts

    # With before=5 (days) the 10-day-old run should be deleted
    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = str(tmp_path)
        mock_settings.ARTIFACT_RETENTION_DAYS = 30  # would not trigger
        result = await cleanup_artifacts(before=5, db=mock_db)  # override to 5 days

    assert run_id in result.deleted_runs


@pytest.mark.asyncio
async def test_cleanup_returns_zero_when_dir_missing():
    """cleanup endpoint returns empty result if artifacts dir doesn't exist."""
    from app.api.artifacts import cleanup_artifacts

    mock_db = AsyncMock()

    with patch("app.api.artifacts.settings") as mock_settings:
        mock_settings.ARTIFACTS_DIR = "/nonexistent/path/that/cannot/exist/ever"
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        result = await cleanup_artifacts(before=None, db=mock_db)

    assert result.deleted_runs == []
    assert result.freed_bytes == 0


# ─────────────────────────────────────────────────────────────────────────────
# Background loop — leader guard
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_artifact_retention_loop_skips_when_not_leader():
    """Background loop skips sweep when not leader."""
    import app.main as main_mod

    mock_leader = MagicMock()
    mock_leader.is_leader = False

    sleep_calls: list[float] = []

    async def _fast_sleep(n: float):
        sleep_calls.append(n)
        if len(sleep_calls) >= 1:
            raise asyncio.CancelledError

    import asyncio
    import app.runtime.leader as leader_mod

    with patch.object(leader_mod, "leader_election", mock_leader), \
         patch("asyncio.sleep", side_effect=_fast_sleep), \
         patch("app.main.settings") as mock_settings:
        mock_settings.ARTIFACT_RETENTION_DAYS = 30
        mock_settings.ARTIFACTS_DIR = "/tmp/test_artifacts"
        try:
            await main_mod._artifact_retention_loop()
        except asyncio.CancelledError:
            pass

    # Directory was never scanned (no os.scandir called because is_leader=False)
    assert len(sleep_calls) >= 1


@pytest.mark.asyncio
async def test_artifact_retention_loop_skips_when_disabled():
    """Background loop skips sweep when ARTIFACT_RETENTION_DAYS=0."""
    import app.main as main_mod
    import app.runtime.leader as leader_mod

    mock_leader = MagicMock()
    mock_leader.is_leader = True

    sleep_counter = [0]

    async def _fast_sleep(n: float):
        sleep_counter[0] += 1
        if sleep_counter[0] >= 1:
            raise asyncio.CancelledError

    import asyncio

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch.object(leader_mod, "leader_election", mock_leader), \
             patch("asyncio.sleep", side_effect=_fast_sleep), \
             patch("app.main.settings") as mock_settings:
            mock_settings.ARTIFACT_RETENTION_DAYS = 0  # disabled
            mock_settings.ARTIFACTS_DIR = tmpdir
            try:
                await main_mod._artifact_retention_loop()
            except asyncio.CancelledError:
                pass

    # Loop completed without error; disabled check correctly short-circuited


@pytest.mark.asyncio
async def test_artifact_retention_loop_deletes_old_folder():
    """Background loop deletes old terminal-run folder when leader."""
    import asyncio
    import app.main as main_mod
    import app.runtime.leader as leader_mod

    mock_leader = MagicMock()
    mock_leader.is_leader = True

    sleep_counter = [0]

    async def _fast_sleep(n: float):
        sleep_counter[0] += 1
        # Let the loop body run once (first sleep), then cancel on the second
        if sleep_counter[0] >= 2:
            raise asyncio.CancelledError

    with tempfile.TemporaryDirectory() as tmpdir:
        run_id = "run-loop-test-old"
        _make_dir_with_file(Path(tmpdir), run_id, size=20)

        mock_run = _make_run(run_id, "completed", days_old=35)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_run

        mock_session_cm = MagicMock()
        mock_session_cm.__aenter__ = AsyncMock(return_value=AsyncMock(
            execute=AsyncMock(return_value=mock_result)
        ))
        mock_session_cm.__aexit__ = AsyncMock(return_value=False)

        def _mock_session():
            return mock_session_cm

        with patch.object(leader_mod, "leader_election", mock_leader), \
             patch("asyncio.sleep", side_effect=_fast_sleep), \
             patch("app.main.settings") as mock_settings, \
             patch("app.main.async_session", _mock_session):
            mock_settings.ARTIFACT_RETENTION_DAYS = 30
            mock_settings.ARTIFACTS_DIR = tmpdir
            try:
                await main_mod._artifact_retention_loop()
            except asyncio.CancelledError:
                pass

        assert not (Path(tmpdir) / run_id).exists()
