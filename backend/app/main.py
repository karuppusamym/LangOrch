"""FastAPI application entry point."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db.engine import engine
from app.db.models import Base

# Routers
from app.api.procedures import router as procedures_router
from app.api.runs import router as runs_router
from app.api.approvals import router as approvals_router
from app.api.events import router as events_router
from app.api.agents import router as agents_router
from app.api.catalog import router as catalog_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create tables on startup (dev convenience — use Alembic in prod)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
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


@app.get("/api/health")
async def health():
    return {"status": "ok"}
