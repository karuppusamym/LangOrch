"""Platform configuration API.

Exposes a safe read/write interface over ``app.config.Settings``.

Endpoints
---------
GET  /api/config        — read current (non-secret) settings       [admin]
PATCH /api/config       — update runtime-mutable settings          [admin]

Secret fields (secrets keys, raw DB passwords) are never returned.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.auth.deps import get_current_user, Principal
from app.auth.roles import require_role
from app.config import settings

logger = logging.getLogger("langorch.api.config")
router = APIRouter(tags=["config"])


# ── Public read schema (subset of Settings - no secrets) ───────────────

class ConfigOut(BaseModel):
    # Server
    host: str
    port: int
    debug: bool
    cors_origins: list[str]

    # Database
    db_dialect: str
    db_host: str
    db_port: int
    db_name: str
    db_pool_size: int
    db_max_overflow: int

    # Auth
    auth_enabled: bool
    auth_token_expire_minutes: int

    # Worker
    worker_embedded: bool | None
    worker_concurrency: int
    worker_poll_interval: float
    worker_max_attempts: int
    worker_retry_delay_seconds: float
    worker_lock_duration_seconds: float

    # LLM
    llm_base_url: str
    llm_timeout_seconds: float
    llm_key_set: bool  # True if LLM_API_KEY is configured (no value exposed)

    # Retention
    checkpoint_retention_days: int
    artifact_retention_days: int

    # Lease
    lease_ttl_seconds: int

    # Metrics
    metrics_push_url: str | None
    metrics_push_interval_seconds: int
    metrics_push_job: str

    # Alerts
    alert_webhook_url: str | None

    # Rate limiting
    rate_limit_max_concurrent: int

    # Secrets
    secrets_rotation_check: bool


class ConfigPatch(BaseModel):
    """Only runtime-mutable fields that don't require a restart."""
    debug: bool | None = None
    cors_origins: list[str] | None = None
    auth_enabled: bool | None = None
    auth_token_expire_minutes: int | None = None
    worker_concurrency: int | None = None
    worker_poll_interval: float | None = None
    worker_max_attempts: int | None = None
    worker_retry_delay_seconds: float | None = None
    checkpoint_retention_days: int | None = None
    artifact_retention_days: int | None = None
    lease_ttl_seconds: int | None = None
    llm_base_url: str | None = None
    llm_timeout_seconds: float | None = None
    alert_webhook_url: str | None = None
    metrics_push_url: str | None = None
    metrics_push_interval_seconds: int | None = None
    rate_limit_max_concurrent: int | None = None
    secrets_rotation_check: bool | None = None


def _build_config_out() -> ConfigOut:
    s = settings
    return ConfigOut(
        host=s.HOST,
        port=s.PORT,
        debug=s.DEBUG,
        cors_origins=s.CORS_ORIGINS,
        db_dialect=s.ORCH_DB_DIALECT,
        db_host=s.ORCH_DB_HOST,
        db_port=s.ORCH_DB_PORT,
        db_name=s.ORCH_DB_NAME,
        db_pool_size=s.ORCH_DB_POOL_SIZE,
        db_max_overflow=s.ORCH_DB_MAX_OVERFLOW,
        auth_enabled=s.AUTH_ENABLED,
        auth_token_expire_minutes=s.AUTH_TOKEN_EXPIRE_MINUTES,
        worker_embedded=s.WORKER_EMBEDDED,
        worker_concurrency=s.WORKER_CONCURRENCY,
        worker_poll_interval=s.WORKER_POLL_INTERVAL,
        worker_max_attempts=s.WORKER_MAX_ATTEMPTS,
        worker_retry_delay_seconds=s.WORKER_RETRY_DELAY_SECONDS,
        worker_lock_duration_seconds=s.WORKER_LOCK_DURATION_SECONDS,
        llm_base_url=s.LLM_BASE_URL,
        llm_timeout_seconds=s.LLM_TIMEOUT_SECONDS,
        llm_key_set=bool(s.LLM_API_KEY),
        checkpoint_retention_days=s.CHECKPOINT_RETENTION_DAYS,
        artifact_retention_days=s.ARTIFACT_RETENTION_DAYS,
        lease_ttl_seconds=s.LEASE_TTL_SECONDS,
        metrics_push_url=s.METRICS_PUSH_URL,
        metrics_push_interval_seconds=s.METRICS_PUSH_INTERVAL_SECONDS,
        metrics_push_job=s.METRICS_PUSH_JOB,
        alert_webhook_url=s.ALERT_WEBHOOK_URL,
        rate_limit_max_concurrent=s.RATE_LIMIT_MAX_CONCURRENT,
        secrets_rotation_check=s.SECRETS_ROTATION_CHECK,
    )


# ── Routes ──────────────────────────────────────────────────────────────

@router.get("/api/config", response_model=ConfigOut)
async def get_config(
    _: Principal = Depends(require_role("admin")),
) -> ConfigOut:
    """Return current platform configuration (non-secret fields)."""
    return _build_config_out()


@router.patch("/api/config", response_model=ConfigOut)
async def patch_config(
    body: ConfigPatch,
    _: Principal = Depends(require_role("admin")),
) -> ConfigOut:
    """Hot-patch runtime-mutable configuration fields.

    Changes take effect immediately in-process.  They are NOT persisted to
    disk — set the corresponding environment variable or .env entry for
    permanent changes.
    """
    updates: dict[str, Any] = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No fields to update")

    # Map patch field names → Settings attribute names
    field_map = {
        "debug": "DEBUG",
        "cors_origins": "CORS_ORIGINS",
        "auth_enabled": "AUTH_ENABLED",
        "auth_token_expire_minutes": "AUTH_TOKEN_EXPIRE_MINUTES",
        "worker_concurrency": "WORKER_CONCURRENCY",
        "worker_poll_interval": "WORKER_POLL_INTERVAL",
        "worker_max_attempts": "WORKER_MAX_ATTEMPTS",
        "worker_retry_delay_seconds": "WORKER_RETRY_DELAY_SECONDS",
        "checkpoint_retention_days": "CHECKPOINT_RETENTION_DAYS",
        "artifact_retention_days": "ARTIFACT_RETENTION_DAYS",
        "lease_ttl_seconds": "LEASE_TTL_SECONDS",
        "llm_base_url": "LLM_BASE_URL",
        "llm_timeout_seconds": "LLM_TIMEOUT_SECONDS",
        "alert_webhook_url": "ALERT_WEBHOOK_URL",
        "metrics_push_url": "METRICS_PUSH_URL",
        "metrics_push_interval_seconds": "METRICS_PUSH_INTERVAL_SECONDS",
        "rate_limit_max_concurrent": "RATE_LIMIT_MAX_CONCURRENT",
        "secrets_rotation_check": "SECRETS_ROTATION_CHECK",
    }

    for patch_field, value in updates.items():
        attr = field_map.get(patch_field)
        if attr:
            object.__setattr__(settings, attr, value)
            logger.info("Config patched: %s = %r", attr, value)

    return _build_config_out()
