"""Trigger registration and firing service."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.compiler.ir import IRTrigger
from app.db.models import Procedure, Run, TriggerDedupeRecord, TriggerRegistration
from app.services.run_service import create_run

logger = logging.getLogger("langorch.trigger_service")


# ── Registration ────────────────────────────────────────────────


async def upsert_trigger(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    trigger: IRTrigger | None = None,
    override: dict[str, Any] | None = None,
) -> TriggerRegistration:
    """Create or update a TriggerRegistration for a procedure version.

    Accepts either an ``IRTrigger`` (parsed from CKP) or a manual ``override`` dict.
    """
    if trigger is None and override is None:
        raise ValueError("Either trigger or override must be supplied")

    existing = await get_trigger(db, procedure_id, version)

    if trigger is not None:
        t_type = trigger.type
        schedule = trigger.schedule
        webhook_secret = trigger.webhook_secret
        event_source = trigger.event_source
        dedupe_window = trigger.dedupe_window_seconds
        max_concurrent = trigger.max_concurrent_runs
    else:
        # Manual override dict
        t_type = override["trigger_type"]
        schedule = override.get("schedule")
        webhook_secret = override.get("webhook_secret")
        event_source = override.get("event_source")
        dedupe_window = int(override.get("dedupe_window_seconds", 0))
        max_concurrent = override.get("max_concurrent_runs")

    now = datetime.now(timezone.utc)
    if existing:
        existing.trigger_type = t_type
        existing.schedule = schedule
        existing.webhook_secret = webhook_secret
        existing.event_source = event_source
        existing.dedupe_window_seconds = dedupe_window
        existing.max_concurrent_runs = max_concurrent
        existing.enabled = override.get("enabled", True) if override else True
        existing.updated_at = now
        await db.flush()
        await db.refresh(existing)
        return existing
    else:
        reg = TriggerRegistration(
            procedure_id=procedure_id,
            version=version,
            trigger_type=t_type,
            schedule=schedule,
            webhook_secret=webhook_secret,
            event_source=event_source,
            dedupe_window_seconds=dedupe_window,
            max_concurrent_runs=max_concurrent,
            enabled=override.get("enabled", True) if override else True,
        )
        db.add(reg)
        await db.flush()
        await db.refresh(reg)
        return reg


async def deregister_trigger(db: AsyncSession, procedure_id: str, version: str) -> bool:
    """Disable (soft-delete) a trigger registration. Returns True if found."""
    reg = await get_trigger(db, procedure_id, version)
    if not reg:
        return False
    reg.enabled = False
    reg.updated_at = datetime.now(timezone.utc)
    await db.flush()
    return True


async def get_trigger(db: AsyncSession, procedure_id: str, version: str) -> TriggerRegistration | None:
    stmt = select(TriggerRegistration).where(
        and_(
            TriggerRegistration.procedure_id == procedure_id,
            TriggerRegistration.version == version,
        )
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def list_trigger_registrations(
    db: AsyncSession,
    enabled_only: bool = False,
) -> list[TriggerRegistration]:
    stmt = select(TriggerRegistration).order_by(TriggerRegistration.procedure_id)
    if enabled_only:
        stmt = stmt.where(TriggerRegistration.enabled.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


# ── Sync from procedure store ────────────────────────────────────


async def sync_triggers_from_procedures(db: AsyncSession) -> int:
    """Scan all procedures with trigger_config_json and upsert TriggerRegistrations.

    Returns the number of registrations created/updated.
    """
    from app.compiler.parser import _parse_trigger  # local import to avoid cycle
    stmt = select(Procedure).where(Procedure.trigger_config_json.isnot(None))
    result = await db.execute(stmt)
    procs = list(result.scalars().all())

    count = 0
    for proc in procs:
        try:
            raw = json.loads(proc.trigger_config_json)  # type: ignore[arg-type]
            ir_trigger = _parse_trigger(raw)
            if ir_trigger and ir_trigger.type != "manual":
                await upsert_trigger(db, proc.procedure_id, proc.version, trigger=ir_trigger)
                count += 1
        except Exception:
            logger.exception("Failed to sync trigger for %s v%s", proc.procedure_id, proc.version)
    return count


# ── Deduplification ─────────────────────────────────────────────


def compute_payload_hash(body: bytes) -> str:
    return hashlib.sha256(body).hexdigest()


async def check_dedupe(
    db: AsyncSession,
    procedure_id: str,
    payload_hash: str,
    window_seconds: int,
) -> str | None:
    """Return existing run_id if a duplicate payload was received within the window, else None."""
    if window_seconds <= 0:
        return None
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=window_seconds)
    stmt = select(TriggerDedupeRecord).where(
        and_(
            TriggerDedupeRecord.procedure_id == procedure_id,
            TriggerDedupeRecord.payload_hash == payload_hash,
            TriggerDedupeRecord.created_at >= cutoff,
        )
    ).order_by(TriggerDedupeRecord.created_at.desc()).limit(1)
    result = await db.execute(stmt)
    record = result.scalar_one_or_none()
    return record.run_id if record else None


async def record_dedupe(
    db: AsyncSession,
    procedure_id: str,
    run_id: str,
    payload_hash: str,
) -> None:
    record = TriggerDedupeRecord(
        procedure_id=procedure_id,
        payload_hash=payload_hash,
        run_id=run_id,
    )
    db.add(record)
    await db.flush()


# ── Firing ──────────────────────────────────────────────────────


async def fire_trigger(
    db: AsyncSession,
    procedure_id: str,
    version: str,
    trigger_type: str,
    triggered_by: str,
    input_vars: dict[str, Any] | None = None,
    project_id: str | None = None,
) -> Run:
    """Create a run tagged with trigger metadata."""
    # Enforce max_concurrent_runs if configured
    reg = await get_trigger(db, procedure_id, version)
    if reg and reg.max_concurrent_runs:
        active_stmt = select(Run).where(
            and_(
                Run.procedure_id == procedure_id,
                Run.procedure_version == version,
                Run.status.in_(["created", "running"]),
            )
        )
        active_result = await db.execute(active_stmt)
        active_count = len(active_result.scalars().all())
        if active_count >= reg.max_concurrent_runs:
            raise RuntimeError(
                f"max_concurrent_runs ({reg.max_concurrent_runs}) reached for "
                f"{procedure_id} v{version} — trigger dropped"
            )

    # Resolve project_id from procedure if not supplied
    if project_id is None:
        proc = await db.get(Procedure, _find_pk(procedure_id, version))
        # Procedure uses composite key — query instead
        stmt = select(Procedure).where(
            and_(
                Procedure.procedure_id == procedure_id,
                Procedure.version == version,
            )
        )
        result = await db.execute(stmt)
        proc = result.scalar_one_or_none()
        if proc:
            project_id = proc.project_id

    run = await create_run(
        db=db,
        procedure_id=procedure_id,
        procedure_version=version,
        input_vars=input_vars,
        project_id=project_id,
        trigger_type=trigger_type,
        triggered_by=triggered_by,
    )
    return run


def _find_pk(procedure_id: str, version: str) -> Any:
    """Placeholder — Procedure uses int PK, not composite."""
    return None


# ── HMAC signature verification ─────────────────────────────────


def verify_hmac_signature(body: bytes, header_signature: str | None, secret_env_var: str) -> bool:
    """Verify HMAC-SHA256 signature.

    Expects header in the form ``sha256=<hex>``, and the secret loaded from
    the environment variable named ``secret_env_var``.
    Returns True when signature is valid OR when no secret is configured.
    """
    secret_value = os.environ.get(secret_env_var, "")
    if not secret_value:
        # No secret configured — allow all (dev mode)
        logger.warning("No webhook secret configured for env var %s — skipping HMAC check", secret_env_var)
        return True
    if not header_signature:
        return False
    # Strip "sha256=" prefix
    sig = header_signature.removeprefix("sha256=")
    expected = hashlib.sha256(f"{secret_value}".encode() + body).hexdigest()
    # Constant-time comparison
    return hashlib.sha256(sig.encode()).hexdigest() == hashlib.sha256(expected.encode()).hexdigest()
