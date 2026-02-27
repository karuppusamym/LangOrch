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
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import get_current_user, Principal
from app.auth.roles import require_role
from app.config import settings
from app.db.engine import get_db

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

    # LLM & Apigee
    llm_base_url: str
    llm_timeout_seconds: float
    llm_key_set: bool  # True if LLM_API_KEY is configured (no value exposed)
    llm_default_model: str
    llm_gateway_headers: str | None
    llm_model_cost_json: str | None
    
    apigee_enabled: bool
    apigee_token_url: str | None
    apigee_certs_path: str | None
    apigee_consumer_key: str | None
    apigee_client_secret: str | None
    apigee_use_case_id: str | None
    apigee_client_id: str | None

    # SSO
    sso_enabled: bool

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
    llm_api_key: str | None = None
    llm_default_model: str | None = None
    llm_gateway_headers: str | None = None
    llm_model_cost_json: str | None = None
    apigee_enabled: bool | None = None
    apigee_token_url: str | None = None
    apigee_certs_path: str | None = None
    apigee_consumer_key: str | None = None
    apigee_client_secret: str | None = None
    apigee_use_case_id: str | None = None
    apigee_client_id: str | None = None
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
        llm_default_model=s.LLM_DEFAULT_MODEL,
        llm_gateway_headers=s.LLM_GATEWAY_HEADERS,
        llm_model_cost_json=s.LLM_MODEL_COST_JSON,
        apigee_enabled=s.APIGEE_ENABLED,
        apigee_token_url=s.APIGEE_TOKEN_URL,
        apigee_certs_path=s.APIGEE_CERTS_PATH,
        apigee_consumer_key=s.APIGEE_CONSUMER_KEY,
        apigee_client_secret=s.APIGEE_CLIENT_SECRET,
        apigee_use_case_id=s.APIGEE_USE_CASE_ID,
        apigee_client_id=s.APIGEE_CLIENT_ID,
        sso_enabled=s.SSO_ENABLED,
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
    principal: Principal = Depends(require_role("admin")),
    db: AsyncSession = Depends(get_db),
) -> ConfigOut:
    """Hot-patch runtime-mutable configuration fields.

    Changes take effect immediately in-process.  They are NOT persisted to
    disk — set the corresponding environment variable or .env entry for
    permanent changes.
    """
    # Use exclude_unset=True so explicitly-null values (i.e. clearing a field)
    # are included, while fields never mentioned in the request body are skipped.
    updates: dict[str, Any] = body.model_dump(exclude_unset=True)
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
        "llm_api_key": "LLM_API_KEY",
        "llm_default_model": "LLM_DEFAULT_MODEL",
        "llm_gateway_headers": "LLM_GATEWAY_HEADERS",
        "llm_model_cost_json": "LLM_MODEL_COST_JSON",
        "apigee_enabled": "APIGEE_ENABLED",
        "apigee_token_url": "APIGEE_TOKEN_URL",
        "apigee_certs_path": "APIGEE_CERTS_PATH",
        "apigee_consumer_key": "APIGEE_CONSUMER_KEY",
        "apigee_client_secret": "APIGEE_CLIENT_SECRET",
        "apigee_use_case_id": "APIGEE_USE_CASE_ID",
        "apigee_client_id": "APIGEE_CLIENT_ID",
        "alert_webhook_url": "ALERT_WEBHOOK_URL",
        "metrics_push_url": "METRICS_PUSH_URL",
        "metrics_push_interval_seconds": "METRICS_PUSH_INTERVAL_SECONDS",
        "rate_limit_max_concurrent": "RATE_LIMIT_MAX_CONCURRENT",
        "secrets_rotation_check": "SECRETS_ROTATION_CHECK",
    }

    # Track which settings were effectively changed
    changed_env_keys = []
    
    for patch_field, value in updates.items():
        attr = field_map.get(patch_field)
        if attr:
            object.__setattr__(settings, attr, value)
            changed_env_keys.append((attr, value))
            logger.info("Config patched: %s = %r", attr, value)

    # Persist changes to DB
    if changed_env_keys:
        import json
        from sqlalchemy import text, select
        from app.api.secrets import _encrypt
        from app.db.models import SecretEntry
        
        # We use a raw SQL UPSERT since we already support sqlite/postgres
        # Using SQLAlchemy ORM for UPSERT is strictly dialect-specific
        try:
            for attr, value in changed_env_keys:
                if attr == "LLM_API_KEY":
                    existing = await db.execute(select(SecretEntry).where(SecretEntry.name == attr))
                    entry = existing.scalar_one_or_none()
                    if value:
                        enc_val = _encrypt(str(value))
                        if entry:
                            entry.encrypted_value = enc_val
                            entry.updated_by = principal.identity
                        else:
                            new_entry = SecretEntry(
                                name=attr,
                                encrypted_value=enc_val,
                                description="LLM Provider API Key",
                                provider_hint="",
                                tags_json="[]",
                                created_by=principal.identity,
                                updated_by=principal.identity,
                            )
                            db.add(new_entry)
                    else:
                        if entry:
                            await db.delete(entry)
                    continue

                if value is None:
                    # Clearing a field — delete the row so it resets to the env/default
                    del_stmt = text("DELETE FROM system_settings WHERE key = :k")
                    await db.execute(del_stmt, {"k": attr})
                    continue

                v_json = json.dumps(value)
                # SQLite-compatible UPSERT
                stmt = text(
                    "INSERT INTO system_settings (key, value_json, updated_at) "
                    "VALUES (:k, :v, CURRENT_TIMESTAMP) "
                    "ON CONFLICT(key) DO UPDATE SET value_json=:v, updated_at=CURRENT_TIMESTAMP"
                )
                if not settings.is_sqlite:
                    # PostgreSQL-compatible UPSERT
                    stmt = text(
                        "INSERT INTO system_settings (key, value_json) "
                        "VALUES (:k, :v) "
                        "ON CONFLICT (key) DO UPDATE SET value_json = EXCLUDED.value_json, updated_at = CURRENT_TIMESTAMP"
                    )
                await db.execute(stmt, {"k": attr, "v": v_json})
        except Exception as _e:
            logger.warning("Failed to persist config to DB: %s", _e)

    from app.api.audit import emit_audit
    await emit_audit(
        db,
        category="config",
        action="patch",
        actor=principal.identity,
        description=f"Platform config patched: {list(updates.keys())}",
        meta={k: str(v) for k, v in updates.items()},
    )
    await db.commit()
    return _build_config_out()


class LLMTestResult(BaseModel):
    ok: bool
    model: str | None = None
    response: str | None = None
    error: str | None = None


@router.post("/api/config/test-llm", response_model=LLMTestResult)
async def test_llm_connection(
    _: Principal = Depends(require_role("admin")),
) -> LLMTestResult:
    """Fire a minimal LLM request to verify the current endpoint + key are reachable."""
    from app.connectors.llm_client import LLMClient, LLMCallError
    try:
        client = LLMClient()
        result = client.complete(
            prompt='Respond with exactly the word: OK',
            model=settings.LLM_DEFAULT_MODEL,
            max_tokens=10,
            temperature=0.0,
        )
        return LLMTestResult(
            ok=True,
            model=result["usage"].get("model") or settings.LLM_DEFAULT_MODEL,
            response=(result.get("text") or "").strip()[:120],
        )
    except LLMCallError as exc:
        return LLMTestResult(ok=False, error=str(exc))
    except Exception as exc:
        return LLMTestResult(ok=False, error=f"{type(exc).__name__}: {exc}")
