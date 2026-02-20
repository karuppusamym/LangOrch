"""Triggers API — webhook receiver, trigger registration CRUD, and manual fire."""

from __future__ import annotations

import asyncio
import logging
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Header, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session, get_db
from app.schemas.triggers import (
    TriggerFireOut,
    TriggerRegistrationCreate,
    TriggerRegistrationOut,
    WebhookFireOut,
)
from app.services import trigger_service
from app.services.execution_service import execute_run

logger = logging.getLogger("langorch.api.triggers")

router = APIRouter()


# ── Webhook receiver ────────────────────────────────────────────


@router.post(
    "/webhook/{procedure_id}",
    response_model=WebhookFireOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Receive a webhook trigger for a procedure",
)
async def receive_webhook(
    procedure_id: str,
    request: Request,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    x_langorch_signature: Annotated[str | None, Header()] = None,
):
    """Receive a POST webhook that fires a procedure run.

    The caller should include an ``X-LangOrch-Signature: sha256=<hmac>`` header
    when a ``webhook_secret`` is configured for this trigger.  Duplicate payloads
    (same SHA-256 body hash within ``dedupe_window_seconds``) are rejected with
    HTTP 409 and the original ``run_id`` is returned.
    """
    # Read raw body (needed for HMAC + dedupe hash)
    body = await request.body()

    # Find the latest enabled trigger registration for this procedure
    all_regs = await trigger_service.list_trigger_registrations(db, enabled_only=True)
    candidates = [r for r in all_regs if r.procedure_id == procedure_id]
    if not candidates:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"No active trigger registration found for procedure '{procedure_id}'",
        )
    # Pick latest version
    reg = candidates[-1]

    # HMAC verification
    if reg.webhook_secret:
        if not trigger_service.verify_hmac_signature(body, x_langorch_signature, reg.webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or missing webhook signature",
            )

    # Deduplification
    payload_hash = trigger_service.compute_payload_hash(body)
    if reg.dedupe_window_seconds > 0:
        existing_run_id = await trigger_service.check_dedupe(
            db, procedure_id, payload_hash, reg.dedupe_window_seconds
        )
        if existing_run_id:
            logger.info(
                "Webhook dedupe hit for %s — returning existing run %s",
                procedure_id, existing_run_id,
            )
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "message": "Duplicate webhook payload within dedupe window",
                    "existing_run_id": existing_run_id,
                },
            )

    # Parse body as JSON input_vars (best-effort — empty dict on failure)
    import json as _json
    try:
        input_vars = _json.loads(body) if body else {}
        if not isinstance(input_vars, dict):
            input_vars = {"payload": input_vars}
    except Exception:
        input_vars = {}

    # Fire the trigger
    try:
        run = await trigger_service.fire_trigger(
            db=db,
            procedure_id=procedure_id,
            version=reg.version,
            trigger_type="webhook",
            triggered_by=f"webhook:{request.client.host if request.client else 'unknown'}",
            input_vars=input_vars,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    # Record dedupe entry
    if reg.dedupe_window_seconds > 0:
        await trigger_service.record_dedupe(db, procedure_id, run.run_id, payload_hash)

    await db.commit()

    # Launch execution in background
    background.add_task(execute_run, run.run_id, async_session)

    return WebhookFireOut(
        run_id=run.run_id,
        procedure_id=procedure_id,
        procedure_version=reg.version,
    )


# ── Manual trigger fire ─────────────────────────────────────────


@router.post(
    "/{procedure_id}/{version}/fire",
    response_model=TriggerFireOut,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Manually fire a trigger (any type) for a specific procedure version",
)
async def fire_trigger_manual(
    procedure_id: str,
    version: str,
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    """Create a run via the trigger system, tagged as trigger_type=manual."""
    reg = await trigger_service.get_trigger(db, procedure_id, version)

    try:
        run = await trigger_service.fire_trigger(
            db=db,
            procedure_id=procedure_id,
            version=version,
            trigger_type=reg.trigger_type if reg else "manual",
            triggered_by="api:manual",
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    await db.commit()
    background.add_task(execute_run, run.run_id, async_session)

    return TriggerFireOut(
        run_id=run.run_id,
        procedure_id=procedure_id,
        procedure_version=version,
        trigger_type=reg.trigger_type if reg else "manual",
        triggered_by="api:manual",
    )


# ── Registration CRUD ───────────────────────────────────────────


@router.get(
    "",
    response_model=list[TriggerRegistrationOut],
    summary="List all trigger registrations",
)
async def list_triggers(db: AsyncSession = Depends(get_db)):
    return await trigger_service.list_trigger_registrations(db)


@router.get(
    "/{procedure_id}/{version}",
    response_model=TriggerRegistrationOut | None,
    summary="Get trigger registration for a procedure version (null if none registered)",
)
async def get_trigger(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    return await trigger_service.get_trigger(db, procedure_id, version)


@router.post(
    "/{procedure_id}/{version}",
    response_model=TriggerRegistrationOut,
    status_code=status.HTTP_201_CREATED,
    summary="Create or update a trigger registration for a procedure version",
)
async def upsert_trigger(
    procedure_id: str,
    version: str,
    body: TriggerRegistrationCreate,
    db: AsyncSession = Depends(get_db),
):
    reg = await trigger_service.upsert_trigger(
        db,
        procedure_id=procedure_id,
        version=version,
        override=body.model_dump(),
    )
    await db.commit()

    # If it's a scheduled trigger, sync the scheduler immediately
    if reg.trigger_type == "scheduled":
        from app.runtime.scheduler import scheduler
        asyncio.create_task(scheduler.sync_schedules())

    return reg


@router.delete(
    "/{procedure_id}/{version}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Disable a trigger registration",
)
async def delete_trigger(procedure_id: str, version: str, db: AsyncSession = Depends(get_db)):
    found = await trigger_service.deregister_trigger(db, procedure_id, version)
    if not found:
        raise HTTPException(status_code=404, detail="Trigger registration not found")
    await db.commit()


@router.post(
    "/sync",
    summary="Sync trigger registrations from all procedures with trigger_config_json",
)
async def sync_triggers(db: AsyncSession = Depends(get_db)):
    """Re-read all procedures and register/update triggers from their CKP trigger blocks."""
    count = await trigger_service.sync_triggers_from_procedures(db)
    await db.commit()

    # Immediately sync scheduler jobs
    from app.runtime.scheduler import scheduler
    asyncio.create_task(scheduler.sync_schedules())

    return {"synced": count}
