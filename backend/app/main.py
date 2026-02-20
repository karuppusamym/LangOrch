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
    ]
    async with engine.begin() as conn:
        for stmt in _new_cols:
            try:
                await conn.execute(__import__("sqlalchemy").text(stmt))
            except Exception:
                pass  # column already exists — ignore
    _expiry_task = asyncio.create_task(_approval_expiry_loop())
    _health_task = asyncio.create_task(_agent_health_loop())
    try:
        yield
    finally:
        _expiry_task.cancel()
        _health_task.cancel()
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
