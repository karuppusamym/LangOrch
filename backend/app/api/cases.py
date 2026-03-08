"""Cases API router."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.audit import emit_audit
from app.db.engine import get_db
from app.schemas.cases import (
    CaseClaimRequest,
    CaseCreate,
    CaseEventOut,
    CaseOut,
    CaseQueueItemOut,
    CaseQueueAnalyticsOut,
    CaseReleaseRequest,
    CaseSlaPolicyCreate,
    CaseSlaPolicyOut,
    CaseSlaPolicyUpdate,
    CaseWebhookSubscriptionCreate,
    CaseWebhookDeliveryOut,
    CaseWebhookDeliveryCountOut,
    CaseWebhookPurgeOut,
    CaseWebhookPurgeSelectedIn,
    CaseWebhookPurgeSelectedOut,
    CaseWebhookDeliverySummaryOut,
    CaseWebhookReplayOut,
    CaseWebhookReplaySelectedIn,
    CaseWebhookSubscriptionOut,
    CaseUpdate,
)
from app.services import case_service, case_sla_policy_service, case_webhook_service, project_service

router = APIRouter()


@router.get("", response_model=list[CaseOut])
async def list_cases(
    project_id: str | None = None,
    status: str | None = None,
    owner: str | None = None,
    external_ref: str | None = None,
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await case_service.list_cases(
        db=db,
        project_id=project_id,
        status=status,
        owner=owner,
        external_ref=external_ref,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/queue", response_model=list[CaseQueueItemOut])
async def list_case_queue(
    project_id: str | None = None,
    owner: str | None = None,
    only_unassigned: bool = False,
    include_terminal: bool = False,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await case_service.list_queue_cases(
        db=db,
        project_id=project_id,
        owner=owner,
        only_unassigned=only_unassigned,
        include_terminal=include_terminal,
        limit=limit,
        offset=offset,
    )


@router.get("/queue/analytics", response_model=CaseQueueAnalyticsOut)
async def get_case_queue_analytics(
    project_id: str | None = None,
    risk_window_minutes: int = Query(default=60, ge=1, le=24 * 60),
    db: AsyncSession = Depends(get_db),
):
    return await case_service.get_queue_analytics(
        db=db,
        project_id=project_id,
        risk_window_minutes=risk_window_minutes,
    )


@router.post("", response_model=CaseOut, status_code=201)
async def create_case(body: CaseCreate, db: AsyncSession = Depends(get_db)):
    if body.project_id:
        proj = await project_service.get_project(db, body.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")

    return await case_service.create_case(
        db=db,
        title=body.title,
        project_id=body.project_id,
        external_ref=body.external_ref,
        case_type=body.case_type,
        description=body.description,
        status=body.status,
        priority=body.priority,
        owner=body.owner,
        sla_due_at=body.sla_due_at,
        tags=body.tags,
        metadata=body.metadata,
    )


@router.get("/webhooks", response_model=list[CaseWebhookSubscriptionOut])
async def list_case_webhooks(
    project_id: str | None = None,
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    return await case_webhook_service.list_subscriptions(
        db,
        project_id=project_id,
        enabled_only=enabled_only,
    )


@router.post("/webhooks", response_model=CaseWebhookSubscriptionOut, status_code=201)
async def create_case_webhook(body: CaseWebhookSubscriptionCreate, db: AsyncSession = Depends(get_db)):
    if body.project_id:
        proj = await project_service.get_project(db, body.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
    try:
        return await case_webhook_service.create_subscription(
            db,
            event_type=body.event_type,
            target_url=body.target_url,
            project_id=body.project_id,
            secret_env_var=body.secret_env_var,
            enabled=body.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/webhooks/deliveries", response_model=list[CaseWebhookDeliveryOut])
async def list_case_webhook_deliveries(
    status: str | None = Query(default=None, pattern="^(pending|processing|retrying|delivered|failed)$"),
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    sort_by: str = Query(default="created_at", pattern="^(created_at|updated_at|attempts)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await case_webhook_service.list_deliveries(
        db,
        status=status,
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/webhooks/dlq", response_model=list[CaseWebhookDeliveryOut])
async def list_case_webhook_dlq(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    sort_by: str = Query(default="updated_at", pattern="^(created_at|updated_at|attempts)$"),
    order: str = Query(default="desc", pattern="^(asc|desc)$"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    return await case_webhook_service.list_deliveries(
        db,
        status="failed",
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        sort_by=sort_by,
        order=order,
        limit=limit,
        offset=offset,
    )


@router.get("/webhooks/dlq/count", response_model=CaseWebhookDeliveryCountOut)
async def count_case_webhook_dlq(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    older_than_hours: int | None = Query(default=None, ge=0, le=24 * 365),
    db: AsyncSession = Depends(get_db),
):
    total = await case_webhook_service.count_deliveries(
        db,
        status="failed",
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        older_than_hours=older_than_hours,
    )
    return CaseWebhookDeliveryCountOut(total=total)


@router.get("/webhooks/deliveries/summary", response_model=CaseWebhookDeliverySummaryOut)
async def get_case_webhook_delivery_summary(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    return await case_webhook_service.get_delivery_summary(
        db,
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
    )


@router.post("/webhooks/deliveries/{delivery_id}/replay", response_model=CaseWebhookReplayOut)
async def replay_case_webhook_delivery(delivery_id: str, db: AsyncSession = Depends(get_db)):
    try:
        delivery = await case_webhook_service.replay_delivery(db, delivery_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    if not delivery:
        raise HTTPException(status_code=404, detail="Webhook delivery not found")
    await db.commit()
    return CaseWebhookReplayOut(replayed=1, delivery_ids=[delivery.delivery_id])


@router.post("/webhooks/deliveries/replay-failed", response_model=CaseWebhookReplayOut)
async def replay_failed_case_webhook_deliveries(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    delivery_ids = await case_webhook_service.replay_failed_deliveries(
        db,
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        limit=limit,
    )
    await db.commit()
    return CaseWebhookReplayOut(replayed=len(delivery_ids), delivery_ids=delivery_ids)


@router.post("/webhooks/dlq/replay", response_model=CaseWebhookReplayOut)
async def replay_case_webhook_dlq(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
):
    delivery_ids = await case_webhook_service.replay_failed_deliveries(
        db,
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        limit=limit,
    )
    await db.commit()
    return CaseWebhookReplayOut(replayed=len(delivery_ids), delivery_ids=delivery_ids)


@router.post("/webhooks/dlq/purge", response_model=CaseWebhookPurgeOut)
async def purge_case_webhook_dlq(
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    older_than_hours: int | None = Query(default=None, ge=0, le=24 * 365),
    limit: int = Query(default=500, ge=1, le=5000),
    db: AsyncSession = Depends(get_db),
):
    deleted = await case_webhook_service.purge_failed_deliveries(
        db,
        subscription_id=subscription_id,
        case_id=case_id,
        event_type=event_type,
        older_than_hours=older_than_hours,
        limit=limit,
    )
    await emit_audit(
        db,
        category="case_webhook",
        action="purge",
        actor="system",
        description=(
            "Purged failed webhook deliveries"
            f" (deleted={deleted}, case_id={case_id or '-'},"
            f" subscription_id={subscription_id or '-'}, event_type={event_type or '-'},"
            f" older_than_hours={older_than_hours if older_than_hours is not None else '-'}, limit={limit})"
        ),
        resource_type="case_webhook_delivery",
        resource_id=case_id or subscription_id,
        meta={
            "deleted": deleted,
            "case_id": case_id,
            "subscription_id": subscription_id,
            "event_type": event_type,
            "older_than_hours": older_than_hours,
            "limit": limit,
        },
    )
    await db.commit()
    return CaseWebhookPurgeOut(deleted=deleted)


@router.post("/webhooks/dlq/replay-selected", response_model=CaseWebhookReplayOut)
async def replay_case_webhook_dlq_selected(
    body: CaseWebhookReplaySelectedIn,
    db: AsyncSession = Depends(get_db),
):
    result = await case_webhook_service.replay_selected_deliveries(
        db,
        delivery_ids=body.delivery_ids,
    )
    await db.commit()
    replayed_ids = result["replayed_ids"]
    return CaseWebhookReplayOut(
        replayed=len(replayed_ids),
        delivery_ids=replayed_ids,
        skipped_non_failed_ids=result["skipped_non_failed_ids"],
        not_found_ids=result["not_found_ids"],
    )


@router.post("/webhooks/dlq/purge-selected", response_model=CaseWebhookPurgeSelectedOut)
async def purge_case_webhook_dlq_selected(
    body: CaseWebhookPurgeSelectedIn,
    db: AsyncSession = Depends(get_db),
):
    result = await case_webhook_service.purge_selected_deliveries(
        db,
        delivery_ids=body.delivery_ids,
    )
    await emit_audit(
        db,
        category="case_webhook",
        action="purge_selected",
        actor="system",
        description=(
            "Purged selected failed webhook deliveries"
            f" (requested={len(body.delivery_ids)}, deleted={len(result['deleted_ids'])},"
            f" skipped_non_failed={len(result['skipped_non_failed_ids'])},"
            f" not_found={len(result['not_found_ids'])})"
        ),
        resource_type="case_webhook_delivery",
        meta={
            "requested_delivery_ids": body.delivery_ids,
            "deleted_delivery_ids": result["deleted_ids"],
            "skipped_non_failed_ids": result["skipped_non_failed_ids"],
            "not_found_ids": result["not_found_ids"],
        },
    )
    await db.commit()
    deleted_ids = result["deleted_ids"]
    return CaseWebhookPurgeSelectedOut(
        deleted=len(deleted_ids),
        delivery_ids=deleted_ids,
        skipped_non_failed_ids=result["skipped_non_failed_ids"],
        not_found_ids=result["not_found_ids"],
    )


@router.delete("/webhooks/{subscription_id}", status_code=204)
async def delete_case_webhook(subscription_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await case_webhook_service.delete_subscription(db, subscription_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Webhook subscription not found")
    return None


@router.get("/sla-policies", response_model=list[CaseSlaPolicyOut])
async def list_sla_policies(
    project_id: str | None = None,
    case_type: str | None = None,
    priority: str | None = None,
    enabled_only: bool = False,
    db: AsyncSession = Depends(get_db),
):
    return await case_sla_policy_service.list_policies(
        db,
        project_id=project_id,
        case_type=case_type,
        priority=priority,
        enabled_only=enabled_only,
    )


@router.post("/sla-policies", response_model=CaseSlaPolicyOut, status_code=201)
async def create_sla_policy(body: CaseSlaPolicyCreate, db: AsyncSession = Depends(get_db)):
    if body.project_id:
        proj = await project_service.get_project(db, body.project_id)
        if not proj:
            raise HTTPException(status_code=404, detail="Project not found")
    return await case_sla_policy_service.create_policy(
        db,
        name=body.name,
        project_id=body.project_id,
        case_type=body.case_type,
        priority=body.priority,
        due_minutes=body.due_minutes,
        breach_status=body.breach_status,
        enabled=body.enabled,
    )


@router.patch("/sla-policies/{policy_id}", response_model=CaseSlaPolicyOut)
async def patch_sla_policy(policy_id: str, body: CaseSlaPolicyUpdate, db: AsyncSession = Depends(get_db)):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        policy = await case_sla_policy_service.get_policy(db, policy_id)
        if not policy:
            raise HTTPException(status_code=404, detail="SLA policy not found")
        return policy
    policy = await case_sla_policy_service.update_policy(db, policy_id, patch)
    if not policy:
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return policy


@router.delete("/sla-policies/{policy_id}", status_code=204)
async def delete_sla_policy(policy_id: str, db: AsyncSession = Depends(get_db)):
    deleted = await case_sla_policy_service.delete_policy(db, policy_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="SLA policy not found")
    return None


@router.get("/{case_id}", response_model=CaseOut)
async def get_case(case_id: str, db: AsyncSession = Depends(get_db)):
    case = await case_service.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.patch("/{case_id}", response_model=CaseOut)
async def patch_case(case_id: str, body: CaseUpdate, db: AsyncSession = Depends(get_db)):
    patch = body.model_dump(exclude_unset=True)
    if not patch:
        case = await case_service.get_case(db, case_id)
        if not case:
            raise HTTPException(status_code=404, detail="Case not found")
        return case

    case = await case_service.update_case(db, case_id, patch)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.post("/{case_id}/claim", response_model=CaseOut)
async def claim_case(case_id: str, body: CaseClaimRequest, db: AsyncSession = Depends(get_db)):
    try:
        case = await case_service.claim_case(
            db,
            case_id=case_id,
            owner=body.owner,
            set_in_progress=body.set_in_progress,
            actor=body.owner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.post("/{case_id}/release", response_model=CaseOut)
async def release_case(case_id: str, body: CaseReleaseRequest, db: AsyncSession = Depends(get_db)):
    try:
        case = await case_service.release_case(
            db,
            case_id=case_id,
            owner=body.owner,
            set_open=body.set_open,
            actor=body.owner,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return case


@router.delete("/{case_id}", status_code=204)
async def delete_case(case_id: str, db: AsyncSession = Depends(get_db)):
    try:
        deleted = await case_service.delete_case(db, case_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc))

    if not deleted:
        raise HTTPException(status_code=404, detail="Case not found")
    return None


@router.get("/{case_id}/events", response_model=list[CaseEventOut])
async def list_case_events(case_id: str, limit: int = Query(default=200, ge=1, le=1000), db: AsyncSession = Depends(get_db)):
    case = await case_service.get_case(db, case_id)
    if not case:
        raise HTTPException(status_code=404, detail="Case not found")
    return await case_service.list_case_events(db, case_id, limit=limit)
