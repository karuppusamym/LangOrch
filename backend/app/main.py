"""FastAPI application entry point."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.config import settings
from app.db.engine import engine, async_session
from app.db.models import Base

# Routers
from app.api.procedures import router as procedures_router
from app.api.runs import router as runs_router
from app.api.approvals import router as approvals_router
from app.api.events import router as events_router
from app.api.agents import router as agents_router
from app.api.orchestrators import router as orchestrators_router
from app.api.catalog import router as catalog_router
from app.api.leases import router as leases_router
from app.api.projects import router as projects_router
from app.api.triggers import router as triggers_router
from app.api.artifacts import router as artifacts_router
from app.api.auth import router as auth_router
from app.api.users import router as users_router
from app.api.secrets import router as secrets_router
from app.api.config import router as config_router
from app.api.audit import router as audit_router
from app.api.agent_credentials import router as agent_credentials_router

from app.utils.logger import setup_logger
logger = setup_logger(log_format=settings.LOG_FORMAT, log_level="DEBUG" if settings.DEBUG else "INFO")
_EXPIRY_POLL_INTERVAL = 30  # seconds
_HEALTH_POLL_INTERVAL = 60  # seconds


_CIRCUIT_OPEN_THRESHOLD = 3  # consecutive failures before opening circuit
_CIRCUIT_RESET_SECONDS = 300  # auto-reset circuit after 5 min


async def _agent_health_loop() -> None:
    """Background task: ping every registered agent's /health endpoint,
    update status, and manage circuit breaker state."""
    import httpx
    from datetime import datetime, timezone
    from sqlalchemy import select
    from app.db.models import AgentInstance

    while True:
        await asyncio.sleep(_HEALTH_POLL_INTERVAL)
        try:
            async with async_session() as db:
                result = await db.execute(select(AgentInstance))
                agents = result.scalars().all()
                changed = 0
                now = datetime.now(timezone.utc)
                async with httpx.AsyncClient(timeout=5.0) as client:
                    for agent in agents:
                        # Auto-reset circuit after threshold
                        if agent.circuit_open_at is not None:
                            # SQLite may return naive datetimes — treat as UTC
                            circuit_ts = agent.circuit_open_at
                            if circuit_ts.tzinfo is None:
                                circuit_ts = circuit_ts.replace(tzinfo=timezone.utc)
                            elapsed = (now - circuit_ts).total_seconds()
                            if elapsed >= _CIRCUIT_RESET_SECONDS:
                                agent.circuit_open_at = None
                                agent.consecutive_failures = 0
                                agent.updated_at = now
                                changed += 1
                                logger.info(
                                    "Circuit reset for agent %s after %ds", agent.agent_id, elapsed
                                )
                                continue  # don't ping until next cycle
                        try:
                            r = await client.get(f"{agent.base_url.rstrip('/')}/health")
                            is_ok = r.status_code == 200
                        except Exception:
                            is_ok = False

                        new_status = "online" if is_ok else "offline"
                        if is_ok:
                            if agent.consecutive_failures > 0 or agent.status != "online":
                                agent.consecutive_failures = 0
                                agent.circuit_open_at = None
                                agent.status = "online"
                                agent.updated_at = now
                                changed += 1
                        else:
                            agent.consecutive_failures = (agent.consecutive_failures or 0) + 1
                            agent.status = "offline"
                            agent.updated_at = now
                            changed += 1
                            if agent.consecutive_failures >= _CIRCUIT_OPEN_THRESHOLD and agent.circuit_open_at is None:
                                agent.circuit_open_at = now
                                logger.warning(
                                    "Circuit OPEN for agent %s after %d consecutive failures",
                                    agent.agent_id, agent.consecutive_failures,
                                )
                if changed:
                    await db.commit()
                    logger.info("Updated status for %d agent(s)", changed)
        except Exception:
            logger.exception("Error in agent health loop")


async def _approval_expiry_loop() -> None:
    """Background task: auto-timeout expired pending approvals.

    Only the current scheduler leader runs this loop.  Under multi-replica
    deployments non-leaders skip each cycle to avoid double-timeouts.
    """
    from app.runtime.leader import leader_election
    from app.services.approval_service import get_expired_approvals, submit_decision

    while True:
        await asyncio.sleep(_EXPIRY_POLL_INTERVAL)
        if not leader_election.is_leader:
            logger.debug("approval_expiry_loop: not leader — skipping")
            continue
        try:
            async with async_session() as db:
                expired = await get_expired_approvals(db)
                for appr in expired:
                    await submit_decision(db, appr.approval_id, "timeout")
                if expired:
                    await db.commit()
                    logger.info("Auto-timed-out %d approval(s)", len(expired))
        except Exception:
            logger.exception("Error in approval expiry loop")


async def _workflow_timeout_loop() -> None:
    """Background task: auto-timeout stalled paused workflow runs.

    Only the current scheduler leader runs this loop. Under multi-replica
    deployments non-leaders skip each cycle to avoid double-timeouts.
    """
    from app.runtime.leader import leader_election
    from app.services.run_service import auto_fail_stalled_workflows

    while True:
        await asyncio.sleep(_EXPIRY_POLL_INTERVAL)
        if not leader_election.is_leader:
            continue
        try:
            async with async_session() as db:
                timeout_mins = settings.WORKFLOW_CALLBACK_TIMEOUT_MINUTES
                if timeout_mins and timeout_mins > 0:
                    failed_runs = await auto_fail_stalled_workflows(db, timeout_mins)
                    if failed_runs:
                        logger.info("Auto-timed-out %d stalled workflow(s): %s", len(failed_runs), failed_runs)
        except Exception:
            logger.exception("Error in workflow timeout loop")


_RETENTION_POLL_INTERVAL = 3600  # hourly
_FILE_WATCH_POLL_INTERVAL = 60   # every minute


async def _checkpoint_retention_loop() -> None:
    """Background task: prune RunEvent rows for runs older than CHECKPOINT_RETENTION_DAYS."""
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import delete, select
    from app.db.models import RunEvent, Run

    while True:
        await asyncio.sleep(_RETENTION_POLL_INTERVAL)
        retention_days = settings.CHECKPOINT_RETENTION_DAYS
        if not retention_days or retention_days <= 0:
            continue
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        try:
            async with async_session() as db:
                # Find runs older than cutoff that are terminal (completed/failed/canceled)
                result = await db.execute(
                    select(Run.run_id).where(
                        Run.created_at < cutoff,
                        Run.status.in_(["completed", "failed", "canceled"]),
                    )
                )
                old_run_ids = [r for (r,) in result.all()]
                if not old_run_ids:
                    continue
                # Prune events for those runs in batches
                deleted = await db.execute(
                    delete(RunEvent).where(RunEvent.run_id.in_(old_run_ids))
                )
                await db.commit()
                pruned = deleted.rowcount
                if pruned:
                    logger.info(
                        "Retention: pruned %d run_event rows for %d runs older than %d days",
                        pruned, len(old_run_ids), retention_days,
                    )
        except Exception:
            logger.exception("Error in checkpoint retention loop")


async def _artifact_retention_loop() -> None:
    """Background task: delete artifact folders for terminal runs older than ARTIFACT_RETENTION_DAYS.

    Layout: ARTIFACTS_DIR/<run_id>/  (created by Batch 28 run-scoped paths)
    Only the scheduler leader runs this loop to prevent concurrent deletes.

    Strategy:
    1. Stat each sub-directory in ARTIFACTS_DIR.
    2. If the directory name looks like a run_id, check the corresponding Run row.
    3. If the Run is terminal (completed/failed/canceled) AND created_at < cutoff → delete.
    4. If no Run row found AND folder is older than cutoff by mtime → delete (orphan cleanup).
    """
    import os
    import shutil
    from datetime import datetime, timezone, timedelta
    from sqlalchemy import select
    from app.db.models import Run
    from app.runtime.leader import leader_election

    while True:
        await asyncio.sleep(_RETENTION_POLL_INTERVAL)
        if not leader_election.is_leader:
            logger.debug("artifact_retention_loop: not leader — skipping")
            continue
        retention_days = settings.ARTIFACT_RETENTION_DAYS
        if not retention_days or retention_days <= 0:
            continue
        cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
        artifacts_dir = os.path.abspath(settings.ARTIFACTS_DIR)
        if not os.path.isdir(artifacts_dir):
            continue
        deleted_dirs: list[str] = []
        freed_bytes: int = 0
        try:
            with os.scandir(artifacts_dir) as it:
                entries = [e for e in it if e.is_dir(follow_symlinks=False)]
        except Exception:
            logger.exception("artifact_retention_loop: cannot scan %s", artifacts_dir)
            continue

        for entry in entries:
            run_id = entry.name
            try:
                async with async_session() as db:
                    result = await db.execute(
                        select(Run).where(Run.run_id == run_id)
                    )
                    run = result.scalar_one_or_none()

                should_delete = False
                if run is not None:
                    if run.status not in ("completed", "failed", "canceled"):
                        continue  # active run — never delete
                    run_ts = run.created_at
                    if run_ts is not None and run_ts.tzinfo is None:
                        run_ts = run_ts.replace(tzinfo=timezone.utc)
                    if run_ts is not None and run_ts < cutoff:
                        should_delete = True
                else:
                    # Orphan folder (no DB row) — fall back to folder mtime
                    folder_mtime = datetime.fromtimestamp(entry.stat().st_mtime, tz=timezone.utc)
                    if folder_mtime < cutoff:
                        should_delete = True

                if should_delete:
                    # Measure size before deleting
                    folder_path = entry.path
                    size = sum(
                        f.stat().st_size
                        for f in os.scandir(folder_path)
                        if f.is_file()
                    )
                    shutil.rmtree(folder_path, ignore_errors=True)
                    deleted_dirs.append(run_id)
                    freed_bytes += size
                    logger.info(
                        "artifact_retention: deleted %s (%d bytes)", run_id, size
                    )
            except Exception:
                logger.exception(
                    "artifact_retention_loop: error processing folder %s", run_id
                )

        if deleted_dirs:
            logger.info(
                "Artifact retention: removed %d folder(s), freed ~%d bytes",
                len(deleted_dirs), freed_bytes,
            )


async def _config_sync_loop() -> None:
    """Background task: Periodically synchronize DB system_settings into in-memory settings.
    Provides HA synchronization across multiple LangOrch workers/containers."""
    from sqlalchemy import text, select
    from app.db.models import SecretEntry
    import json

    while True:
        await asyncio.sleep(30)
        try:
            async with async_session() as db:
                # Sync standard settings
                result = await db.execute(text("SELECT key, value_json FROM system_settings"))
                for key, value_json in result.all():
                    try:
                        val = json.loads(value_json)
                        if getattr(settings, key, None) != val:
                            setattr(settings, key, val)
                            logger.info("HA Sync: Reloaded config override %s", key)
                    except Exception:
                        pass
                
                # Sync secrets
                try:
                    from app.api.secrets import _decrypt
                    res = await db.execute(select(SecretEntry).where(SecretEntry.name == "LLM_API_KEY"))
                    entry = res.scalar_one_or_none()
                    if entry:
                        decrypted = _decrypt(entry.encrypted_value)
                        if settings.LLM_API_KEY != decrypted:
                            settings.LLM_API_KEY = decrypted
                            logger.info("HA Sync: Reloaded LLM_API_KEY from secrets")
                except Exception:
                    pass
        except Exception as exc:
            logger.debug("Error in config sync loop: %s", exc)


async def _file_watch_trigger_loop() -> None:
    """Background task: poll file_watch trigger registrations and fire runs when files change.

    Only the current scheduler leader runs this loop.  Non-leaders skip each
    poll cycle; once leadership is acquired the baseline mtime is recorded on
    the next cycle so no spurious fires occur.
    """
    import os
    from sqlalchemy import select
    from app.db.models import TriggerRegistration
    from app.runtime.leader import leader_election

    # Track last-seen mtime per trigger registration id
    _last_mtime: dict[int, float] = {}

    while True:
        await asyncio.sleep(_FILE_WATCH_POLL_INTERVAL)
        if not leader_election.is_leader:
            logger.debug("file_watch_trigger_loop: not leader — skipping")
            # Clear cached mtimes so the new leader re-baselines on first cycle
            _last_mtime.clear()
            continue
        try:
            async with async_session() as db:
                result = await db.execute(
                    select(TriggerRegistration).where(
                        TriggerRegistration.trigger_type == "file_watch",
                        TriggerRegistration.enabled == True,  # noqa: E712
                    )
                )
                registrations = result.scalars().all()

            for reg in registrations:
                try:
                    # event_source stores the watch path for file_watch triggers
                    watch_path = reg.event_source
                    if not watch_path:
                        continue
                    if not os.path.exists(watch_path):
                        continue

                    current_mtime = os.path.getmtime(watch_path)
                    reg_key = reg.id
                    last_mtime = _last_mtime.get(reg_key)

                    if last_mtime is None:
                        # First observation — record baseline, don't fire
                        _last_mtime[reg_key] = current_mtime
                        continue

                    if current_mtime > last_mtime:
                        _last_mtime[reg_key] = current_mtime
                        logger.info(
                            "file_watch: change detected on %s — firing trigger for %s:%s",
                            watch_path, reg.procedure_id, reg.version,
                        )
                        try:
                            from app.services.trigger_service import fire_trigger
                            async with async_session() as db:
                                await fire_trigger(
                                    db,
                                    procedure_id=reg.procedure_id,
                                    version=reg.version,
                                    trigger_type="file_watch",
                                    triggered_by=watch_path,
                                    input_vars={"file_watch_path": watch_path, "file_mtime": current_mtime},
                                )
                                await db.commit()
                        except Exception:
                            logger.exception(
                                "file_watch: failed to fire trigger for %s:%s",
                                reg.procedure_id, reg.version,
                            )
                except Exception:
                    logger.exception("file_watch: error processing registration id=%s", reg.id)
        except Exception:
            logger.exception("Error in file_watch trigger loop")


async def _metrics_push_loop() -> None:
    """Background task: push Prometheus metrics to a Pushgateway on a fixed interval.

    Only runs when ``settings.METRICS_PUSH_URL`` is configured.
    Uses the Prometheus Pushgateway PUT API:
    ``PUT <METRICS_PUSH_URL>/metrics/job/<METRICS_PUSH_JOB>``
    """
    import httpx
    from app.utils.metrics import to_prometheus_text

    push_url = settings.METRICS_PUSH_URL
    if not push_url:
        return  # disabled
    target = f"{push_url.rstrip('/')}/metrics/job/{settings.METRICS_PUSH_JOB}"
    logger.info("Metrics push loop started — target: %s interval: %ds", target, settings.METRICS_PUSH_INTERVAL_SECONDS)

    while True:
        await asyncio.sleep(settings.METRICS_PUSH_INTERVAL_SECONDS)
        try:
            payload = to_prometheus_text()
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.put(
                    target,
                    content=payload.encode(),
                    headers={"Content-Type": "text/plain; version=0.0.4"},
                )
                if resp.status_code not in (200, 202, 204):
                    logger.warning("Metrics push returned HTTP %s", resp.status_code)
                else:
                    logger.debug("Metrics pushed to Pushgateway (%d bytes)", len(payload))
        except Exception as exc:
            logger.warning("Metrics push failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        if settings.is_sqlite:
            try:
                await conn.run_sync(Base.metadata.create_all)
            except Exception as _e:
                logger.warning("create_all partial failure (likely existing index): %s", _e)
                # Tables already exist — safe to continue
        # else: for PostgreSQL, run `alembic upgrade head` before starting the server
    # Idempotent column migrations for new fields (SQLite-safe ADD COLUMN)
    # These are no-ops when the column already exists (catches on duplicate column).
    # For PostgreSQL, Alembic handles all schema changes — these are skipped.
    if settings.is_sqlite:
        _new_cols = [
            "ALTER TABLE runs ADD COLUMN error_message TEXT",
            "ALTER TABLE runs ADD COLUMN parent_run_id VARCHAR(64)",
            "ALTER TABLE runs ADD COLUMN output_vars_json TEXT",
            "ALTER TABLE runs ADD COLUMN total_prompt_tokens INTEGER",
            "ALTER TABLE runs ADD COLUMN total_completion_tokens INTEGER",
            "ALTER TABLE runs ADD COLUMN estimated_cost_usd REAL",
            "ALTER TABLE runs ADD COLUMN trigger_type VARCHAR(32)",
            "ALTER TABLE runs ADD COLUMN triggered_by VARCHAR(256)",
            "ALTER TABLE runs ADD COLUMN cancellation_requested INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE agent_instances ADD COLUMN consecutive_failures INTEGER DEFAULT 0",
            "ALTER TABLE agent_instances ADD COLUMN circuit_open_at DATETIME",
            "ALTER TABLE agent_instances ADD COLUMN last_heartbeat_at DATETIME",
            "ALTER TABLE agent_instances ADD COLUMN pool_id VARCHAR(128)",
            "ALTER TABLE procedures ADD COLUMN trigger_config_json TEXT",
            # Batch 34: artifact metadata columns
            "ALTER TABLE artifacts ADD COLUMN name VARCHAR(512)",
            "ALTER TABLE artifacts ADD COLUMN mime_type VARCHAR(128)",
            "ALTER TABLE artifacts ADD COLUMN size_bytes INTEGER",
            # Batch 29: scheduler_leader_leases table (CREATE TABLE IF NOT EXISTS)
            (
                "CREATE TABLE IF NOT EXISTS scheduler_leader_leases ("
                "  name VARCHAR(64) PRIMARY KEY, "
                "  leader_id VARCHAR(256) NOT NULL, "
                "  acquired_at DATETIME NOT NULL, "
                "  expires_at DATETIME NOT NULL"
                ")"
            ),
            # OrchestratorWorker registry table (migration 194a461733a3)
            (
                "CREATE TABLE IF NOT EXISTS orchestrator_workers ("
                "  worker_id VARCHAR(256) PRIMARY KEY, "
                "  status VARCHAR(32) NOT NULL, "
                "  is_leader BOOLEAN NOT NULL DEFAULT 0, "
                "  last_heartbeat_at DATETIME NOT NULL"
                ")"
            ),
            # Batch 35: audit_events table
            (
                "CREATE TABLE IF NOT EXISTS audit_events ("
                "  event_id INTEGER PRIMARY KEY AUTOINCREMENT, "
                "  ts DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "  category VARCHAR(64) NOT NULL, "
                "  action VARCHAR(64) NOT NULL, "
                "  actor VARCHAR(256) NOT NULL DEFAULT 'system', "
                "  description TEXT NOT NULL DEFAULT '', "
                "  resource_type VARCHAR(64), "
                "  resource_id VARCHAR(256), "
                "  meta_json TEXT"
                ")"
            ),
            (
                "CREATE TABLE IF NOT EXISTS system_settings ("
                "  key VARCHAR(128) PRIMARY KEY, "
                "  value_json TEXT NOT NULL, "
                "  updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP"
                ")"
            ),
            # Batch 38: persistent agent dispatch counters
            (
                "CREATE TABLE IF NOT EXISTS agent_dispatch_counters ("
                "  pool_id VARCHAR(128) PRIMARY KEY, "
                "  counter_value INTEGER NOT NULL DEFAULT 0, "
                "  updated_at DATETIME NOT NULL"
                ")"
            ),
        ]
        async with engine.begin() as conn:
            for stmt in _new_cols:
                try:
                    await conn.execute(__import__("sqlalchemy").text(stmt))
                except Exception:
                    pass  # column already exists — ignore
                    
    # Load persistent system settings overrides from DB into the settings singleton
    try:
        from app.db.engine import async_session as _asm_cfg
        from sqlalchemy import select
        from app.db.models import SecretEntry
        import json
        async with _asm_cfg() as _db_cfg:
            result = await _db_cfg.execute(__import__("sqlalchemy").text("SELECT key, value_json FROM system_settings"))
            for key, value_json in result.all():
                try:
                    val = json.loads(value_json)
                    setattr(settings, key, val)
                    logger.debug("Loaded config override from DB: %s", key)
                except Exception:
                    pass
            
            # Load secure API keys
            try:
                from app.api.secrets import _decrypt
                sec_res = await _db_cfg.execute(select(SecretEntry).where(SecretEntry.name == "LLM_API_KEY"))
                entry = sec_res.scalar_one_or_none()
                if entry:
                    settings.LLM_API_KEY = _decrypt(entry.encrypted_value)
                    logger.debug("Loaded secure LLM_API_KEY from DB")
            except Exception as _sec_e:
                logger.debug("Failed to load secure LLM_API_KEY: %s", _sec_e)

    except Exception as _e:
        logger.warning("Failed to load DB config overrides: %s", _e)
    # Seed default admin user if users table is empty
    try:
        from app.db.engine import async_session as _asm_users
        from app.services.user_service import ensure_default_admin as _seed_admin
        async with _asm_users() as _db_users:
            await _seed_admin(_db_users)
    except Exception as _e:
        logger.warning("Auto-seed admin failed: %s", _e)
    # Start leader election — must be running before any singleton loops check is_leader
    from app.runtime.leader import leader_election as _leader_election
    _leader_election.start()
    # Give the first election attempt a head-start before loop tasks fire
    # (small sleep; SQLite will acquire immediately; PG may need one cycle)
    await asyncio.sleep(0.1)

    logger.info("Application lifespan startup complete — entering serve loop")
    
    # Start background loops
    _expiry_task = asyncio.create_task(_approval_expiry_loop())
    _workflow_t_task = asyncio.create_task(_workflow_timeout_loop())
    _health_task = asyncio.create_task(_agent_health_loop())
    _retention_task = asyncio.create_task(_checkpoint_retention_loop())
    _artifact_retention_task = asyncio.create_task(_artifact_retention_loop())
    _file_watch_task = asyncio.create_task(_file_watch_trigger_loop())
    _metrics_push_task = asyncio.create_task(_metrics_push_loop())
    _config_sync_task = asyncio.create_task(_config_sync_loop())
    # Start trigger scheduler
    from app.runtime.scheduler import scheduler as _trigger_scheduler
    _trigger_scheduler.start()
    # Initial trigger sync from all procedures
    try:
        from app.db.engine import async_session as _asm
        from app.services.trigger_service import sync_triggers_from_procedures as _sync_t
        async with _asm() as _db:
            _count = await _sync_t(_db)
            await _db.commit()
        if _count:
            logger.info("Auto-synced %d trigger registrations from procedures", _count)
    except Exception:
        logger.exception("Initial trigger sync failed")
    # Start embedded durable worker when configured (default for SQLite dev mode)
    _worker_task: asyncio.Task | None = None
    if settings.WORKER_EMBEDDED:
        from app.worker.loop import worker_loop as _worker_loop
        _worker_task = asyncio.create_task(_worker_loop())
        logger.info(
            "Embedded worker started (concurrency=%d, poll_interval=%.1fs)",
            settings.WORKER_CONCURRENCY,
            settings.WORKER_POLL_INTERVAL,
        )
    try:
        yield
    finally:
        _expiry_task.cancel()
        _workflow_t_task.cancel()
        _health_task.cancel()
        _retention_task.cancel()
        _artifact_retention_task.cancel()
        _file_watch_task.cancel()
        _metrics_push_task.cancel()
        _config_sync_task.cancel()
        _trigger_scheduler.stop()
        _leader_election.stop()
        if _worker_task is not None:
            _worker_task.cancel()
        await engine.dispose()


from app.utils.tracing import setup_tracing

app = FastAPI(
    title="LangOrch",
    description="CKP-driven durable agentic orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

# Initialize OpenTelemetry setup (if endpoint is provided in config)
setup_tracing(app, settings.OTLP_ENDPOINT)

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount routers
app.include_router(procedures_router, prefix="/api/procedures", tags=["procedures"])
app.include_router(runs_router, prefix="/api/runs", tags=["runs"])
app.include_router(approvals_router, prefix="/api/approvals", tags=["approvals"])
app.include_router(events_router, prefix="/api", tags=["events"])
app.include_router(agents_router, prefix="/api/agents", tags=["agents"])
app.include_router(orchestrators_router, prefix="/api/orchestrators", tags=["orchestrators"])
app.include_router(catalog_router, prefix="/api", tags=["catalog"])
app.include_router(leases_router, prefix="/api/leases", tags=["leases"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(triggers_router, prefix="/api/triggers", tags=["triggers"])
app.include_router(artifacts_router, prefix="/api/artifacts-admin", tags=["artifacts"])
app.include_router(auth_router, prefix="/api/auth", tags=["auth"])
app.include_router(users_router, prefix="/api/users", tags=["users"])
app.include_router(secrets_router, prefix="/api/secrets", tags=["secrets"])
app.include_router(config_router, tags=["config"])
app.include_router(audit_router)  # prefix is defined in router: /api/audit
app.include_router(agent_credentials_router)

# ── Serve local artifacts as static files ──────────────────────────────────
# Agents write artifacts to ARTIFACTS_DIR and return URIs like
#   /api/artifacts/<run_id>/<filename>
# This mount makes those URIs resolvable directly from the browser / frontend.
import os as _os
_os.makedirs(settings.ARTIFACTS_DIR, exist_ok=True)
app.mount(
    "/api/artifacts",
    StaticFiles(directory=settings.ARTIFACTS_DIR, html=False),
    name="artifacts",
)


@app.get("/api/health")
async def health():
    return {"status": "ok"}


@app.get("/api/metrics", response_class=PlainTextResponse, tags=["observability"])
async def prometheus_metrics():
    """Prometheus-compatible text exposition of in-process metrics.

    Exposes all counters and histogram stats in the Prometheus text format
    so a Prometheus scraper or Grafana agent can ingest them directly.
    Example line: ``langorch_run_started_total 42``
    """
    from app.utils.metrics import to_prometheus_text
    return to_prometheus_text()
