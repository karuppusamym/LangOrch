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
from app.api.catalog import router as catalog_router
from app.api.leases import router as leases_router
from app.api.projects import router as projects_router
from app.api.triggers import router as triggers_router

logger = logging.getLogger("langorch.main")

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
                            elapsed = (now - agent.circuit_open_at).total_seconds()
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
    """Background task: auto-timeout expired pending approvals."""
    from app.services.approval_service import get_expired_approvals, submit_decision

    while True:
        await asyncio.sleep(_EXPIRY_POLL_INTERVAL)
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


async def _file_watch_trigger_loop() -> None:
    """Background task: poll file_watch trigger registrations and fire runs when files change."""
    import os
    from sqlalchemy import select
    from app.db.models import TriggerRegistration

    # Track last-seen mtime per trigger registration id
    _last_mtime: dict[int, float] = {}

    while True:
        await asyncio.sleep(_FILE_WATCH_POLL_INTERVAL)
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


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev convenience — use Alembic in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    # Idempotent column migrations for new fields (SQLite-safe ADD COLUMN)
    _new_cols = [
        "ALTER TABLE runs ADD COLUMN error_message TEXT",
        "ALTER TABLE runs ADD COLUMN parent_run_id VARCHAR(64)",
        "ALTER TABLE runs ADD COLUMN output_vars_json TEXT",
        "ALTER TABLE runs ADD COLUMN total_prompt_tokens INTEGER",
        "ALTER TABLE runs ADD COLUMN total_completion_tokens INTEGER",
        "ALTER TABLE agent_instances ADD COLUMN consecutive_failures INTEGER DEFAULT 0",
        "ALTER TABLE agent_instances ADD COLUMN circuit_open_at DATETIME",
        "ALTER TABLE procedures ADD COLUMN trigger_config_json TEXT",
        "ALTER TABLE runs ADD COLUMN trigger_type VARCHAR(32)",
        "ALTER TABLE runs ADD COLUMN triggered_by VARCHAR(256)",
        "ALTER TABLE runs ADD COLUMN estimated_cost_usd REAL",
    ]
    async with engine.begin() as conn:
        for stmt in _new_cols:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception:
                pass  # column already exists — ignore
    _expiry_task = asyncio.create_task(_approval_expiry_loop())
    _health_task = asyncio.create_task(_agent_health_loop())
    _retention_task = asyncio.create_task(_checkpoint_retention_loop())
    _file_watch_task = asyncio.create_task(_file_watch_trigger_loop())
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
    try:
        yield
    finally:
        _expiry_task.cancel()
        _health_task.cancel()
        _retention_task.cancel()
        _file_watch_task.cancel()
        _trigger_scheduler.stop()
        await engine.dispose()


app = FastAPI(
    title="LangOrch",
    description="CKP-driven durable agentic orchestrator",
    version="0.1.0",
    lifespan=lifespan,
)

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
app.include_router(catalog_router, prefix="/api", tags=["catalog"])
app.include_router(leases_router, prefix="/api/leases", tags=["leases"])
app.include_router(projects_router, prefix="/api/projects", tags=["projects"])
app.include_router(triggers_router, prefix="/api/triggers", tags=["triggers"])

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
    from app.utils.metrics import get_metrics_summary
    summary = get_metrics_summary()
    lines: list[str] = []
    for key, val in summary.get("counters", {}).items():
        prom_key = "langorch_" + key.replace("{", "").replace("}", "").replace(",", "_").replace("=", "_").replace('"', "")
        lines.append(f"# TYPE {prom_key} counter")
        lines.append(f"{prom_key} {val}")
    for key, stats in summary.get("histograms", {}).items():
        prom_key = "langorch_" + key.replace("{", "").replace("}", "").replace(",", "_").replace("=", "_").replace('"', "")
        lines.append(f"# TYPE {prom_key} summary")
        if isinstance(stats, dict):
            if stats.get("count") is not None:
                lines.append(f"{prom_key}_count {stats['count']}")
            if stats.get("sum") is not None:
                lines.append(f"{prom_key}_sum {stats['sum']:.6f}")
            if stats.get("avg") is not None:
                lines.append(f'{prom_key}{{quantile="0.5"}} {stats["avg"]:.6f}')
            if stats.get("p95") is not None:
                lines.append(f'{prom_key}{{quantile="0.95"}} {stats["p95"]:.6f}')
            if stats.get("max") is not None:
                lines.append(f'{prom_key}{{quantile="1.0"}} {stats["max"]:.6f}')
    return "\n".join(lines) + "\n"
