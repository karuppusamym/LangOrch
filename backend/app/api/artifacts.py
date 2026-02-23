"""Artifacts API — manual retention cleanup endpoint.

POST /api/artifacts/cleanup
    Scan ARTIFACTS_DIR for run-scoped sub-folders whose corresponding Run row
    is terminal (completed/failed/canceled) and older than ARTIFACT_RETENTION_DAYS
    (or ``before`` query param) and delete them.

GET /api/artifacts/stats
    Return aggregate size and folder count of the artifact store.
"""

from __future__ import annotations

import logging
import os
import shutil
from datetime import datetime, timezone, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session
from app.db.models import Run

logger = logging.getLogger("langorch.api.artifacts")

router = APIRouter()


# ── response schemas ──────────────────────────────────────────────────────────


class CleanupResult(BaseModel):
    deleted_runs: list[str]
    freed_bytes: int
    skipped: int


class ArtifactStats(BaseModel):
    total_folders: int
    total_bytes: int
    artifacts_dir: str


# ── helpers ───────────────────────────────────────────────────────────────────


async def _get_db():
    async with async_session() as db:
        yield db


def _folder_size(path: str) -> int:
    """Return total size in bytes of all *files* directly inside ``path``."""
    total = 0
    try:
        with os.scandir(path) as it:
            for entry in it:
                if entry.is_file(follow_symlinks=False):
                    try:
                        total += entry.stat().st_size
                    except OSError:
                        pass
    except OSError:
        pass
    return total


# ── endpoints ─────────────────────────────────────────────────────────────────


@router.post("/cleanup", response_model=CleanupResult, tags=["artifacts"])
async def cleanup_artifacts(
    before: int = Query(
        default=None,
        description="Delete folders for terminal runs older than this many days. "
        "Defaults to ARTIFACT_RETENTION_DAYS setting. 0 means clean everything terminal.",
    ),
    db: AsyncSession = Depends(_get_db),
) -> CleanupResult:
    """Delete artifact folders for completed/failed/canceled runs older than *before* days.

    Runs that are still active (running, created, waiting_approval) are never touched.
    Orphaned folders (no matching Run row) are also removed if old enough (by mtime).
    """
    retention_days = before if before is not None else settings.ARTIFACT_RETENTION_DAYS
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)

    artifacts_dir = os.path.abspath(settings.ARTIFACTS_DIR)
    if not os.path.isdir(artifacts_dir):
        return CleanupResult(deleted_runs=[], freed_bytes=0, skipped=0)

    try:
        with os.scandir(artifacts_dir) as it:
            entries = [e for e in it if e.is_dir(follow_symlinks=False)]
    except OSError as exc:
        logger.exception("cleanup_artifacts: cannot scan %s", artifacts_dir)
        raise RuntimeError(f"Cannot scan artifacts dir: {exc}") from exc

    deleted: list[str] = []
    freed = 0
    skipped = 0

    for entry in entries:
        run_id = entry.name
        try:
            result = await db.execute(select(Run).where(Run.run_id == run_id))
            run = result.scalar_one_or_none()

            should_delete = False
            if run is not None:
                if run.status not in ("completed", "failed", "canceled"):
                    skipped += 1
                    continue  # active run — never delete
                run_ts = run.created_at
                if run_ts is not None and run_ts.tzinfo is None:
                    run_ts = run_ts.replace(tzinfo=timezone.utc)
                if run_ts is not None and run_ts < cutoff:
                    should_delete = True
                else:
                    skipped += 1
            else:
                # Orphan folder — use mtime
                folder_mtime = datetime.fromtimestamp(
                    entry.stat().st_mtime, tz=timezone.utc
                )
                if folder_mtime < cutoff:
                    should_delete = True
                else:
                    skipped += 1

            if should_delete:
                size = _folder_size(entry.path)
                shutil.rmtree(entry.path, ignore_errors=True)
                deleted.append(run_id)
                freed += size
                logger.info("cleanup_artifacts: deleted %s (%d bytes)", run_id, size)
        except Exception:
            logger.exception("cleanup_artifacts: error processing %s", run_id)
            skipped += 1

    logger.info(
        "cleanup_artifacts: removed %d folder(s), freed %d bytes, skipped %d",
        len(deleted), freed, skipped,
    )
    return CleanupResult(deleted_runs=deleted, freed_bytes=freed, skipped=skipped)


@router.get("/stats", response_model=ArtifactStats, tags=["artifacts"])
async def artifact_stats() -> ArtifactStats:
    """Return total folder count and disk usage of the artifact store."""
    artifacts_dir = os.path.abspath(settings.ARTIFACTS_DIR)
    total_folders = 0
    total_bytes = 0

    if os.path.isdir(artifacts_dir):
        try:
            with os.scandir(artifacts_dir) as it:
                for entry in it:
                    if entry.is_dir(follow_symlinks=False):
                        total_folders += 1
                        total_bytes += _folder_size(entry.path)
                    elif entry.is_file(follow_symlinks=False):
                        # flat files (pre-Batch-28 artifacts)
                        try:
                            total_bytes += entry.stat().st_size
                        except OSError:
                            pass
        except OSError:
            pass

    return ArtifactStats(
        total_folders=total_folders,
        total_bytes=total_bytes,
        artifacts_dir=artifacts_dir,
    )
