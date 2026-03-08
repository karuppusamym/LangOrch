"""Outbound webhook subscriptions for case events."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db.engine import async_session
from app.db.models import CaseWebhookDelivery, CaseWebhookSubscription

logger = logging.getLogger("langorch.case_webhooks")

SUPPORTED_CASE_EVENTS = {
    "case_created",
    "case_updated",
    "case_claimed",
    "case_released",
    "case_sla_breached",
    "run_linked",
    "*",
}


def _validate_event_type(event_type: str) -> None:
    if event_type not in SUPPORTED_CASE_EVENTS:
        raise ValueError(
            f"Unsupported event_type '{event_type}'. Allowed: {sorted(SUPPORTED_CASE_EVENTS)}"
        )


def _build_signature(payload_bytes: bytes, secret_value: str) -> str:
    sig = hmac.new(secret_value.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()
    return f"sha256={sig}"


def _delivery_idempotency_key(delivery: CaseWebhookDelivery) -> str:
    # Stable across retries for the same logical event/subscription pair.
    if delivery.case_event_id is not None:
        return f"case_event:{delivery.case_event_id}:sub:{delivery.subscription_id}"
    return f"delivery:{delivery.delivery_id}"


def _event_idempotency_key(event: dict[str, Any], subscription_id: str) -> str:
    event_id = event.get("event_id")
    if event_id is not None:
        return f"case_event:{event_id}:sub:{subscription_id}"
    payload_digest = hashlib.sha256(
        json.dumps(event, default=str, sort_keys=True).encode("utf-8")
    ).hexdigest()
    return f"payload:{payload_digest}:sub:{subscription_id}"


async def list_subscriptions(
    db: AsyncSession,
    project_id: str | None = None,
    enabled_only: bool = False,
) -> list[CaseWebhookSubscription]:
    stmt = select(CaseWebhookSubscription).order_by(CaseWebhookSubscription.created_at.desc())
    if project_id:
        stmt = stmt.where(CaseWebhookSubscription.project_id == project_id)
    if enabled_only:
        stmt = stmt.where(CaseWebhookSubscription.enabled.is_(True))
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def create_subscription(
    db: AsyncSession,
    event_type: str,
    target_url: str,
    project_id: str | None = None,
    secret_env_var: str | None = None,
    enabled: bool = True,
) -> CaseWebhookSubscription:
    _validate_event_type(event_type)
    sub = CaseWebhookSubscription(
        event_type=event_type,
        target_url=target_url,
        project_id=project_id,
        secret_env_var=secret_env_var,
        enabled=enabled,
    )
    db.add(sub)
    await db.flush()
    await db.refresh(sub)
    return sub


async def delete_subscription(db: AsyncSession, subscription_id: str) -> bool:
    sub = await db.get(CaseWebhookSubscription, subscription_id)
    if not sub:
        return False
    await db.delete(sub)
    await db.flush()
    return True


async def list_deliveries(
    db: AsyncSession,
    *,
    status: str | None = None,
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    sort_by: str = "created_at",
    order: str = "desc",
    limit: int = 100,
    offset: int = 0,
) -> list[CaseWebhookDelivery]:
    stmt = select(CaseWebhookDelivery)
    if status:
        stmt = stmt.where(CaseWebhookDelivery.status == status)
    if subscription_id:
        stmt = stmt.where(CaseWebhookDelivery.subscription_id == subscription_id)
    if case_id:
        stmt = stmt.where(CaseWebhookDelivery.case_id == case_id)
    if event_type:
        stmt = stmt.where(CaseWebhookDelivery.event_type == event_type)

    sort_columns = {
        "created_at": CaseWebhookDelivery.created_at,
        "updated_at": CaseWebhookDelivery.updated_at,
        "attempts": CaseWebhookDelivery.attempts,
    }
    sort_col = sort_columns.get(sort_by, CaseWebhookDelivery.created_at)
    sort_expr = sort_col.asc() if order == "asc" else sort_col.desc()

    # Stable secondary sort avoids row jitter across pagination boundaries.
    stmt = stmt.order_by(sort_expr, CaseWebhookDelivery.delivery_id.desc()).limit(limit).offset(offset)
    return list((await db.execute(stmt)).scalars().all())


async def count_deliveries(
    db: AsyncSession,
    *,
    status: str | None = None,
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    older_than_hours: int | None = None,
) -> int:
    stmt = select(func.count()).select_from(CaseWebhookDelivery)
    if status:
        stmt = stmt.where(CaseWebhookDelivery.status == status)
    if subscription_id:
        stmt = stmt.where(CaseWebhookDelivery.subscription_id == subscription_id)
    if case_id:
        stmt = stmt.where(CaseWebhookDelivery.case_id == case_id)
    if event_type:
        stmt = stmt.where(CaseWebhookDelivery.event_type == event_type)
    if older_than_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, older_than_hours))
        stmt = stmt.where(CaseWebhookDelivery.updated_at <= cutoff)
    return int((await db.execute(stmt)).scalar() or 0)


async def replay_delivery(db: AsyncSession, delivery_id: str) -> CaseWebhookDelivery | None:
    delivery = await db.get(CaseWebhookDelivery, delivery_id)
    if not delivery:
        return None
    if delivery.status != "failed":
        raise ValueError("Only failed deliveries can be replayed")
    now = datetime.now(timezone.utc)
    delivery.status = "retrying"
    delivery.next_attempt_at = now
    delivery.last_error = None
    delivery.last_status_code = None
    delivery.updated_at = now
    await db.flush()
    return delivery


async def replay_failed_deliveries(
    db: AsyncSession,
    *,
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    limit: int = 100,
) -> list[str]:
    stmt = select(CaseWebhookDelivery).where(CaseWebhookDelivery.status == "failed")
    if subscription_id:
        stmt = stmt.where(CaseWebhookDelivery.subscription_id == subscription_id)
    if case_id:
        stmt = stmt.where(CaseWebhookDelivery.case_id == case_id)
    if event_type:
        stmt = stmt.where(CaseWebhookDelivery.event_type == event_type)
    rows = list(
        (
            await db.execute(
                stmt.order_by(CaseWebhookDelivery.created_at.desc()).limit(max(1, min(limit, 500)))
            )
        ).scalars().all()
    )
    now = datetime.now(timezone.utc)
    replayed: list[str] = []
    for row in rows:
        row.status = "retrying"
        row.next_attempt_at = now
        row.last_error = None
        row.last_status_code = None
        row.updated_at = now
        replayed.append(row.delivery_id)
    if rows:
        await db.flush()
    return replayed


async def purge_failed_deliveries(
    db: AsyncSession,
    *,
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
    older_than_hours: int | None = None,
    limit: int = 500,
) -> int:
    stmt = select(CaseWebhookDelivery.delivery_id).where(CaseWebhookDelivery.status == "failed")
    if subscription_id:
        stmt = stmt.where(CaseWebhookDelivery.subscription_id == subscription_id)
    if case_id:
        stmt = stmt.where(CaseWebhookDelivery.case_id == case_id)
    if event_type:
        stmt = stmt.where(CaseWebhookDelivery.event_type == event_type)
    if older_than_hours is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=max(0, older_than_hours))
        stmt = stmt.where(CaseWebhookDelivery.updated_at <= cutoff)

    purge_limit = max(1, min(int(limit), 5000))
    target_ids = list(
        (
            await db.execute(
                stmt.order_by(CaseWebhookDelivery.updated_at.asc()).limit(purge_limit)
            )
        ).scalars().all()
    )
    if not target_ids:
        return 0

    await db.execute(
        delete(CaseWebhookDelivery).where(CaseWebhookDelivery.delivery_id.in_(target_ids))
    )
    await db.flush()
    return len(target_ids)


async def purge_selected_deliveries(
    db: AsyncSession,
    *,
    delivery_ids: list[str],
) -> dict[str, list[str]]:
    if not delivery_ids:
        return {
            "deleted_ids": [],
            "skipped_non_failed_ids": [],
            "not_found_ids": [],
        }

    requested_ids = list(dict.fromkeys(delivery_ids))
    stmt = select(CaseWebhookDelivery).where(CaseWebhookDelivery.delivery_id.in_(requested_ids))
    rows = list((await db.execute(stmt)).scalars().all())
    by_id = {row.delivery_id: row for row in rows}

    deleted_ids: list[str] = []
    skipped_non_failed_ids: list[str] = []
    not_found_ids: list[str] = []

    for delivery_id in requested_ids:
        row = by_id.get(delivery_id)
        if row is None:
            not_found_ids.append(delivery_id)
            continue
        if row.status != "failed":
            skipped_non_failed_ids.append(delivery_id)
            continue
        await db.delete(row)
        deleted_ids.append(delivery_id)

    if deleted_ids:
        await db.flush()
    return {
        "deleted_ids": deleted_ids,
        "skipped_non_failed_ids": skipped_non_failed_ids,
        "not_found_ids": not_found_ids,
    }


async def replay_selected_deliveries(
    db: AsyncSession,
    *,
    delivery_ids: list[str],
) -> dict[str, list[str]]:
    if not delivery_ids:
        return {
            "replayed_ids": [],
            "skipped_non_failed_ids": [],
            "not_found_ids": [],
        }

    # Preserve request order while removing duplicates.
    requested_ids = list(dict.fromkeys(delivery_ids))

    stmt = select(CaseWebhookDelivery).where(CaseWebhookDelivery.delivery_id.in_(requested_ids))
    rows = list((await db.execute(stmt)).scalars().all())
    by_id = {row.delivery_id: row for row in rows}
    now = datetime.now(timezone.utc)

    replayed_ids: list[str] = []
    skipped_non_failed_ids: list[str] = []
    not_found_ids: list[str] = []

    for delivery_id in requested_ids:
        row = by_id.get(delivery_id)
        if row is None:
            not_found_ids.append(delivery_id)
            continue
        if row.status != "failed":
            skipped_non_failed_ids.append(delivery_id)
            continue

        row.status = "retrying"
        row.next_attempt_at = now
        row.last_error = None
        row.last_status_code = None
        row.updated_at = now
        replayed_ids.append(delivery_id)

    if replayed_ids:
        await db.flush()
    return {
        "replayed_ids": replayed_ids,
        "skipped_non_failed_ids": skipped_non_failed_ids,
        "not_found_ids": not_found_ids,
    }


async def get_delivery_summary(
    db: AsyncSession,
    *,
    subscription_id: str | None = None,
    case_id: str | None = None,
    event_type: str | None = None,
) -> dict[str, Any]:
    filters = []
    if subscription_id:
        filters.append(CaseWebhookDelivery.subscription_id == subscription_id)
    if case_id:
        filters.append(CaseWebhookDelivery.case_id == case_id)
    if event_type:
        filters.append(CaseWebhookDelivery.event_type == event_type)

    total = int(
        (
            await db.execute(
                select(func.count()).select_from(CaseWebhookDelivery).where(*filters)
            )
        ).scalar()
        or 0
    )

    by_status_rows = (
        await db.execute(
            select(CaseWebhookDelivery.status, func.count())
            .where(*filters)
            .group_by(CaseWebhookDelivery.status)
        )
    ).all()
    by_status = {str(status): int(count) for status, count in by_status_rows}

    oldest_pending_ts = (
        await db.execute(
            select(func.min(CaseWebhookDelivery.created_at)).where(
                *filters,
                CaseWebhookDelivery.status.in_(["pending", "retrying", "processing"]),
            )
        )
    ).scalar_one_or_none()

    now = datetime.now(timezone.utc)
    oldest_pending_age: float | None = None
    if oldest_pending_ts is not None:
        created_at = oldest_pending_ts
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        oldest_pending_age = max(0.0, (now - created_at).total_seconds())

    hour_ago = now - timedelta(hours=1)
    recent_failures_last_hour = int(
        (
            await db.execute(
                select(func.count()).select_from(CaseWebhookDelivery).where(
                    *filters,
                    CaseWebhookDelivery.status == "failed",
                    CaseWebhookDelivery.updated_at >= hour_ago,
                )
            )
        ).scalar()
        or 0
    )

    return {
        "total": total,
        "by_status": by_status,
        "oldest_pending_age_seconds": oldest_pending_age,
        "recent_failures_last_hour": recent_failures_last_hour,
    }


async def _matching_subscriptions(
    db: AsyncSession,
    event_type: str,
    project_id: str | None,
    enabled_only: bool = True,
) -> list[CaseWebhookSubscription]:
    stmt = select(CaseWebhookSubscription)
    if enabled_only:
        stmt = stmt.where(CaseWebhookSubscription.enabled.is_(True))
    stmt = stmt.where(
        or_(
            CaseWebhookSubscription.event_type == event_type,
            CaseWebhookSubscription.event_type == "*",
        )
    ).where(
        or_(
            CaseWebhookSubscription.project_id.is_(None),
            CaseWebhookSubscription.project_id == project_id,
        )
    )
    return list((await db.execute(stmt)).scalars().all())


async def enqueue_case_event_webhooks(
    db: AsyncSession,
    event: dict[str, Any],
) -> int:
    """Persist one outbox row per matching webhook subscription.

    Returns number of queued delivery rows.
    """
    event_type = str(event.get("event_type") or "")
    if not event_type:
        return 0
    project_id = event.get("project_id")
    case_event_id = event.get("event_id")
    case_id = event.get("case_id")
    payload_json = json.dumps(event, default=str, sort_keys=True)

    subs = await _matching_subscriptions(db, event_type, project_id, enabled_only=True)
    if not subs:
        return 0

    now = datetime.now(timezone.utc)
    max_attempts = max(1, int(settings.CASE_WEBHOOK_MAX_ATTEMPTS))
    created = 0
    for sub in subs:
        row = CaseWebhookDelivery(
            subscription_id=sub.subscription_id,
            case_event_id=int(case_event_id) if case_event_id is not None else None,
            case_id=str(case_id) if case_id is not None else None,
            project_id=str(project_id) if project_id is not None else None,
            event_type=event_type,
            payload_json=payload_json,
            status="pending",
            attempts=0,
            max_attempts=max_attempts,
            next_attempt_at=now,
        )
        db.add(row)
        created += 1
    await db.flush()
    return created


async def _deliver_once(
    delivery: CaseWebhookDelivery,
    subscription: CaseWebhookSubscription,
    client: httpx.AsyncClient,
) -> tuple[int | None, str | None]:
    try:
        payload = json.loads(delivery.payload_json)
    except (TypeError, ValueError) as exc:
        return None, f"Invalid payload JSON: {exc}"
    if not isinstance(payload, dict):
        return None, "Invalid payload JSON: payload must decode to an object"
    payload_bytes = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")

    headers = {
        "Content-Type": "application/json",
        "X-LangOrch-Event": delivery.event_type,
        "X-LangOrch-Subscription-Id": subscription.subscription_id,
        "X-LangOrch-Delivery-Id": delivery.delivery_id,
        "X-LangOrch-Idempotency-Key": _delivery_idempotency_key(delivery),
    }
    if subscription.secret_env_var:
        secret_val = os.getenv(subscription.secret_env_var)
        if secret_val:
            headers["X-LangOrch-Signature"] = _build_signature(payload_bytes, secret_val)

    try:
        resp = await client.post(subscription.target_url, json=payload, headers=headers)
        if resp.status_code >= 400:
            return resp.status_code, f"HTTP {resp.status_code}"
        return resp.status_code, None
    except Exception as exc:
        return None, str(exc)


def _build_failed_delivery_dlq_payload(delivery: CaseWebhookDelivery) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "subscription_id": delivery.subscription_id,
        "delivery_id": delivery.delivery_id,
    }
    try:
        decoded = json.loads(delivery.payload_json)
    except (TypeError, ValueError):
        decoded = None

    if isinstance(decoded, dict):
        payload["event_data"] = decoded
    else:
        payload["raw_payload_json"] = delivery.payload_json
    return payload


def _retry_delay_seconds(attempts: int) -> int:
    base = max(1, int(settings.CASE_WEBHOOK_RETRY_BASE_SECONDS))
    # Capped exponential backoff: base * 2^(attempts-1), max 15 minutes.
    delay = base * (2 ** max(0, attempts - 1))
    return min(delay, 900)


async def _deliver_to_subscription(db: AsyncSession, subscription_id: str, event_data: dict[str, Any]) -> None:
    """Helper function for DLQ retry: deliver event to a specific subscription.
    
    Used by DLQ retry handler to replay failed webhook deliveries.
    Raises exception on failure for proper DLQ retry handling.
    """
    stmt = select(CaseWebhookSubscription).where(CaseWebhookSubscription.subscription_id == subscription_id)
    result = await db.execute(stmt)
    subscription = result.scalar_one_or_none()
    
    if not subscription:
        raise ValueError(f"Webhook subscription {subscription_id} not found")
    
    if not subscription.enabled:
        raise ValueError(f"Webhook subscription {subscription_id} is disabled")
    
    # Build payload and headers
    payload_bytes = json.dumps(event_data, default=str, sort_keys=True).encode("utf-8")
    event_type = event_data.get("event_type", "unknown")
    
    headers = {
        "Content-Type": "application/json",
        "X-LangOrch-Event": event_type,
        "X-LangOrch-Subscription-Id": subscription_id,
        "X-LangOrch-DLQ-Replay": "true",  # Mark as DLQ replay
    }
    
    if subscription.secret_env_var:
        secret_val = os.getenv(subscription.secret_env_var)
        if secret_val:
            headers["X-LangOrch-Signature"] = _build_signature(payload_bytes, secret_val)
    
    # Attempt delivery
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(subscription.target_url, json=event_data, headers=headers)
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            logger.info(
                f"DLQ replay: Successfully delivered to subscription {subscription_id}, status={resp.status_code}"
            )
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            logger.error(f"DLQ replay: Failed to deliver to subscription {subscription_id}: {exc}")
            raise


async def deliver_webhook(webhook_url: str, event_payload: dict[str, Any], headers: dict[str, str] | None = None) -> None:
    """Generic webhook delivery function for DLQ retry.
    
    Used by DLQ retry handler for generic webhook_delivery events.
    Raises exception on failure.
    """
    if headers is None:
        headers = {}
    
    headers.setdefault("Content-Type", "application/json")
    headers["X-LangOrch-DLQ-Replay"] = "true"
    
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.post(webhook_url, json=event_payload, headers=headers)
            if resp.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}",
                    request=resp.request,
                    response=resp,
                )
            logger.info(f"DLQ replay: Successfully delivered to {webhook_url}, status={resp.status_code}")
        except httpx.HTTPStatusError:
            raise
        except Exception as exc:
            logger.error(f"DLQ replay: Failed to deliver to {webhook_url}: {exc}")
            raise


async def process_pending_deliveries(limit: int | None = None) -> dict[str, int]:
    """Deliver queued/retrying case webhook outbox rows.

    Returns counters: claimed, delivered, retried, failed.
    """
    now = datetime.now(timezone.utc)
    batch_size = int(limit or settings.CASE_WEBHOOK_DELIVERY_BATCH_SIZE)
    batch_size = max(1, min(batch_size, 500))

    async with async_session() as db:
        rows = list(
            (
                await db.execute(
                    select(CaseWebhookDelivery)
                    .where(CaseWebhookDelivery.status.in_(["pending", "retrying"]))
                    .where(CaseWebhookDelivery.next_attempt_at <= now)
                    .order_by(CaseWebhookDelivery.next_attempt_at.asc(), CaseWebhookDelivery.created_at.asc())
                    .limit(batch_size)
                )
            ).scalars().all()
        )
        if not rows:
            return {"claimed": 0, "delivered": 0, "retried": 0, "failed": 0}

        for row in rows:
            row.status = "processing"
            row.updated_at = now
        await db.flush()

        sub_ids = {row.subscription_id for row in rows}
        subs = list(
            (
                await db.execute(
                    select(CaseWebhookSubscription).where(CaseWebhookSubscription.subscription_id.in_(sub_ids))
                )
            ).scalars().all()
        )
        sub_by_id = {sub.subscription_id: sub for sub in subs}

        delivered = 0
        retried = 0
        failed = 0

        async with httpx.AsyncClient(timeout=5.0) as client:
            for row in rows:
                sub = sub_by_id.get(row.subscription_id)
                if not sub or not sub.enabled:
                    row.status = "failed"
                    row.last_error = "Subscription missing or disabled"
                    row.last_status_code = None
                    row.updated_at = now
                    failed += 1
                    continue

                status_code, err = await _deliver_once(row, sub, client)
                if err is None:
                    row.status = "delivered"
                    row.last_status_code = status_code
                    row.last_error = None
                    row.delivered_at = datetime.now(timezone.utc)
                    row.updated_at = datetime.now(timezone.utc)
                    delivered += 1
                    # Record successful delivery metric
                    try:
                        from app.utils.metrics import record_webhook_delivery
                        record_webhook_delivery("delivered", row.event_type)
                    except Exception:
                        pass
                    continue

                row.attempts = int(row.attempts or 0) + 1
                row.last_status_code = status_code
                row.last_error = err
                if row.attempts >= int(row.max_attempts or settings.CASE_WEBHOOK_MAX_ATTEMPTS):
                    row.status = "failed"
                    row.updated_at = datetime.now(timezone.utc)
                    failed += 1
                    # Record failed delivery metric
                    try:
                        from app.utils.metrics import record_webhook_delivery
                        record_webhook_delivery("failed", row.event_type)
                    except Exception:
                        pass
                    # Add to DLQ for later retry/inspection
                    try:
                        from app.services import dlq_service
                        await dlq_service.add_to_dlq(
                            db=db,
                            event_type="webhook_subscription_delivery",
                            payload=_build_failed_delivery_dlq_payload(row),
                            error_message=err,
                            error_type="HTTPError" if status_code else "ConnectionError",
                            http_status_code=status_code,
                            entity_type="webhook_delivery",
                            entity_id=row.delivery_id,
                            original_timestamp=row.created_at,
                            max_retries=3,
                            metadata={"event_type": row.event_type, "subscription_id": row.subscription_id},
                        )
                        logger.info(f"Added failed webhook delivery to DLQ: {row.delivery_id}")
                    except Exception as dlq_exc:
                        logger.error(f"Failed to add webhook delivery to DLQ: {dlq_exc}")
                else:
                    delay = _retry_delay_seconds(row.attempts)
                    row.status = "retrying"
                    row.next_attempt_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
                    row.updated_at = datetime.now(timezone.utc)
                    retried += 1
                    # Record retry metric
                    try:
                        from app.utils.metrics import record_webhook_delivery
                        record_webhook_delivery("retrying", row.event_type)
                    except Exception:
                        pass

        await db.commit()
        if retried or failed:
            logger.warning(
                "case_webhook deliveries processed: claimed=%d delivered=%d retried=%d failed=%d",
                len(rows),
                delivered,
                retried,
                failed,
            )
        return {"claimed": len(rows), "delivered": delivered, "retried": retried, "failed": failed}


async def dispatch_case_event_webhooks(event: dict[str, Any]) -> None:
    """Push one case event payload to all matching subscriptions."""
    event_type = str(event.get("event_type") or "")
    project_id = event.get("project_id")
    if not event_type:
        return

    async with async_session() as db:
        subs = await _matching_subscriptions(db, event_type, project_id, enabled_only=True)

    if not subs:
        return

    payload = dict(event)
    payload_bytes = json.dumps(payload, default=str, sort_keys=True).encode("utf-8")

    async with httpx.AsyncClient(timeout=5.0) as client:
        for sub in subs:
            headers = {
                "Content-Type": "application/json",
                "X-LangOrch-Event": event_type,
                "X-LangOrch-Subscription-Id": sub.subscription_id,
                "X-LangOrch-Idempotency-Key": _event_idempotency_key(event, sub.subscription_id),
            }
            if sub.secret_env_var:
                secret_val = os.getenv(sub.secret_env_var)
                if secret_val:
                    headers["X-LangOrch-Signature"] = _build_signature(payload_bytes, secret_val)
            try:
                resp = await client.post(sub.target_url, json=payload, headers=headers)
                if resp.status_code >= 400:
                    logger.warning(
                        "Case webhook delivery failed: sub=%s status=%s event=%s",
                        sub.subscription_id,
                        resp.status_code,
                        event_type,
                    )
            except Exception as exc:
                logger.warning(
                    "Case webhook delivery exception: sub=%s event=%s err=%s",
                    sub.subscription_id,
                    event_type,
                    exc,
                )


def schedule_case_event_dispatch(event: dict[str, Any]) -> None:
    """Queue webhook deliveries asynchronously (durable outbox producer)."""
    async def _enqueue() -> None:
        async with async_session() as db:
            queued = await enqueue_case_event_webhooks(db, event)
            if queued:
                await db.commit()

    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    loop.create_task(_enqueue())
