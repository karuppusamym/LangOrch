"""Dead-Letter Queue (DLQ) service for event replay and failure recovery.

Handles failed webhook deliveries, callback timeouts, and other retriable events.
Supports bulk retry with rate limiting, event filtering, and automatic replay.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import DeadLetterQueue

logger = logging.getLogger(__name__)


async def add_to_dlq(
    db: AsyncSession,
    event_type: str,
    payload: dict[str, Any],
    error_message: str | None = None,
    error_type: str | None = None,
    http_status_code: int | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    original_timestamp: datetime | None = None,
    max_retries: int = 3,
    metadata: dict[str, Any] | None = None,
    created_by: str = "system",
) -> DeadLetterQueue:
    """Add failed event to dead-letter queue.
    
    Args:
        db: Database session
        event_type: Event classification (webhook_delivery, callback_timeout, etc.)
        payload: Original event payload (will be JSON-encoded)
        error_message: Human-readable error description
        error_type: Error classification (HTTPError, Timeout, ConnectionError, etc.)
        http_status_code: For webhook/HTTP failures
        entity_type: Source entity type (case, run, webhook_subscription, etc.)
        entity_id: Source entity ID
        original_timestamp: When event first occurred (defaults to now)
        max_retries: Maximum retry attempts before marking exhausted
        metadata: Additional context (project_id, priority, tags, etc.)
        created_by: Who/what added this to DLQ
    
    Returns:
        Created DeadLetterQueue record
    """
    if original_timestamp is None:
        original_timestamp = datetime.now(timezone.utc)
    
    # Determine initial status based on error type
    if error_type and error_type.lower() in ("validationerror", "autherror", "notfounderror"):
        # Non-retriable errors
        status = "non_retriable"
    else:
        status = "pending"
    
    dlq_entry = DeadLetterQueue(
        event_type=event_type,
        entity_type=entity_type,
        entity_id=entity_id,
        payload_json=json.dumps(payload),
        original_timestamp=original_timestamp,
        error_message=error_message,
        error_type=error_type,
        http_status_code=http_status_code,
        max_retries=max_retries,
        status=status,
        metadata_json=json.dumps(metadata) if metadata else None,
        created_by=created_by,
    )
    
    db.add(dlq_entry)
    await db.commit()
    await db.refresh(dlq_entry)
    
    logger.warning(
        f"DLQ: Added {event_type} event to dead-letter queue",
        extra={
            "dlq_id": dlq_entry.dlq_id,
            "event_type": event_type,
            "entity_id": entity_id,
            "status": status,
            "error": error_message,
        },
    )
    
    return dlq_entry


async def get_dlq_messages(
    db: AsyncSession,
    event_type: str | None = None,
    status: str | None = None,
    entity_type: str | None = None,
    entity_id: str | None = None,
    failed_after: datetime | None = None,
    failed_before: datetime | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[DeadLetterQueue]:
    """Query DLQ messages with filtering.
    
    Args:
        db: Database session
        event_type: Filter by event type
        status: Filter by status (pending, retrying, succeeded, exhausted, non_retriable)
        entity_type: Filter by entity type
        entity_id: Filter by specific entity ID
        failed_after: Messages failed after this timestamp
        failed_before: Messages failed before this timestamp
        limit: Max results to return (default 100, max 1000)
        offset: Pagination offset
    
    Returns:
        List of matching DLQ entries, ordered by failed_at DESC
    """
    limit = min(limit, 1000)  # Cap at 1000
    
    conditions = []
    
    if event_type:
        conditions.append(DeadLetterQueue.event_type == event_type)
    if status:
        conditions.append(DeadLetterQueue.status == status)
    if entity_type:
        conditions.append(DeadLetterQueue.entity_type == entity_type)
    if entity_id:
        conditions.append(DeadLetterQueue.entity_id == entity_id)
    if failed_after:
        conditions.append(DeadLetterQueue.failed_at >= failed_after)
    if failed_before:
        conditions.append(DeadLetterQueue.failed_at <= failed_before)
    
    stmt = (
        select(DeadLetterQueue)
        .where(and_(*conditions) if conditions else True)
        .order_by(DeadLetterQueue.failed_at.desc())
        .limit(limit)
        .offset(offset)
    )
    
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def count_dlq_messages(
    db: AsyncSession,
    event_type: str | None = None,
    status: str | None = None,
    entity_type: str | None = None,
) -> int:
    """Count DLQ messages matching filters."""
    from sqlalchemy import func
    
    conditions = []
    if event_type:
        conditions.append(DeadLetterQueue.event_type == event_type)
    if status:
        conditions.append(DeadLetterQueue.status == status)
    if entity_type:
        conditions.append(DeadLetterQueue.entity_type == entity_type)
    
    stmt = select(func.count()).select_from(DeadLetterQueue)
    if conditions:
        stmt = stmt.where(and_(*conditions))
    
    result = await db.execute(stmt)
    return result.scalar() or 0


async def retry_dlq_message(
    db: AsyncSession,
    dlq_id: str,
    retry_handler: Any,  # Async callable that performs the actual retry
) -> tuple[bool, str]:
    """Retry a single DLQ message.
    
    Args:
        db: Database session
        dlq_id: DLQ entry ID
        retry_handler: Async function that takes (event_type, payload_dict) and performs retry
    
    Returns:
        (success: bool, message: str)
    """
    stmt = select(DeadLetterQueue).where(DeadLetterQueue.dlq_id == dlq_id)
    result = await db.execute(stmt)
    dlq_entry = result.scalar_one_or_none()
    
    if not dlq_entry:
        return False, f"DLQ entry {dlq_id} not found"
    
    if dlq_entry.status == "succeeded":
        return False, "Message already succeeded"
    
    if dlq_entry.status == "non_retriable":
        return False, "Message marked as non-retriable"
    
    if dlq_entry.retry_count >= dlq_entry.max_retries:
        # Mark as exhausted
        dlq_entry.status = "exhausted"
        await db.commit()
        return False, f"Max retries ({dlq_entry.max_retries}) exhausted"
    
    # Mark as retrying
    dlq_entry.status = "retrying"
    dlq_entry.retry_count += 1
    dlq_entry.last_retry_at = datetime.now(timezone.utc)
    await db.commit()
    
    # Attempt retry
    try:
        payload = json.loads(dlq_entry.payload_json)
        await retry_handler(dlq_entry.event_type, payload, dlq_entry)
        
        # Success: mark as succeeded
        dlq_entry.status = "succeeded"
        dlq_entry.succeeded_at = datetime.now(timezone.utc)
        await db.commit()
        
        logger.info(
            f"DLQ: Successfully retried {dlq_entry.event_type} event",
            extra={"dlq_id": dlq_id, "retry_count": dlq_entry.retry_count},
        )
        return True, "Retry succeeded"
    
    except Exception as e:
        # Retry failed
        error_msg = str(e)
        dlq_entry.error_message = f"{dlq_entry.error_message}\n[Retry {dlq_entry.retry_count}]: {error_msg}"
        
        if dlq_entry.retry_count >= dlq_entry.max_retries:
            dlq_entry.status = "exhausted"
            logger.error(
                f"DLQ: Retry exhausted for {dlq_entry.event_type}",
                extra={"dlq_id": dlq_id, "error": error_msg},
            )
        else:
            dlq_entry.status = "pending"  # Back to pending for next retry
            logger.warning(
                f"DLQ: Retry failed for {dlq_entry.event_type}, will retry again",
                extra={"dlq_id": dlq_id, "retry_count": dlq_entry.retry_count, "error": error_msg},
            )
        
        await db.commit()
        return False, f"Retry failed: {error_msg}"


async def bulk_retry_dlq(
    db: AsyncSession,
    retry_handler: Any,
    event_type: str | None = None,
    status: str | None = None,
    max_messages: int = 100,
    rate_limit_per_second: int = 10,
) -> dict[str, Any]:
    """Bulk retry DLQ messages with rate limiting.
    
    Args:
        db: Database session
        retry_handler: Async function for retrying events
        event_type: Filter by event type
        status: Filter by status (defaults to 'pending')
        max_messages: Max messages to retry in this batch
        rate_limit_per_second: Max retry attempts per second
    
    Returns:
        Summary dict with success_count, failed_count, skipped_count, errors
    """
    if status is None:
        status = "pending"
    
    messages = await get_dlq_messages(
        db,
        event_type=event_type,
        status=status,
        limit=max_messages,
    )
    
    if not messages:
        return {
            "success_count": 0,
            "failed_count": 0,
            "skipped_count": 0,
            "total_processed": 0,
            "errors": [],
        }
    
    success_count = 0
    failed_count = 0
    skipped_count = 0
    errors = []
    
    delay_seconds = 1.0 / rate_limit_per_second if rate_limit_per_second > 0 else 0
    
    logger.info(
        f"DLQ: Starting bulk retry of {len(messages)} messages",
        extra={
            "event_type": event_type,
            "status": status,
            "rate_limit": rate_limit_per_second,
        },
    )
    
    for msg in messages:
        # Rate limiting
        if delay_seconds > 0:
            await asyncio.sleep(delay_seconds)
        
        success, result_msg = await retry_dlq_message(db, msg.dlq_id, retry_handler)
        
        if success:
            success_count += 1
        elif "already succeeded" in result_msg or "non-retriable" in result_msg:
            skipped_count += 1
        else:
            failed_count += 1
            errors.append({"dlq_id": msg.dlq_id, "error": result_msg})
    
    logger.info(
        f"DLQ: Bulk retry completed",
        extra={
            "total": len(messages),
            "success": success_count,
            "failed": failed_count,
            "skipped": skipped_count,
        },
    )
    
    return {
        "success_count": success_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "total_processed": len(messages),
        "errors": errors[:10],  # Limit error list to first 10
    }


async def purge_dlq(
    db: AsyncSession,
    status: str | None = None,
    purge_before: datetime | None = None,
    event_type: str | None = None,
) -> int:
    """Remove messages from DLQ based on status and age.
    
    Args:
        db: Database session
        status: Purge messages with this status (succeeded, exhausted, etc.)
        purge_before: Purge messages failed before this timestamp
        event_type: Filter by event type
    
    Returns:
        Number of messages purged
    """
    conditions = []
    
    if status:
        conditions.append(DeadLetterQueue.status == status)
    if purge_before:
        conditions.append(DeadLetterQueue.failed_at < purge_before)
    if event_type:
        conditions.append(DeadLetterQueue.event_type == event_type)
    
    if not conditions:
        # Safety: require at least one filter to prevent accidental purge of all messages
        raise ValueError("At least one filter (status, purge_before, event_type) must be specified")
    
    stmt = delete(DeadLetterQueue).where(and_(*conditions))
    result = await db.execute(stmt)
    await db.commit()
    
    purged_count = result.rowcount or 0
    
    logger.info(
        f"DLQ: Purged {purged_count} messages",
        extra={
            "status": status,
            "purge_before": purge_before,
            "event_type": event_type,
        },
    )
    
    return purged_count


async def get_dlq_stats(db: AsyncSession) -> dict[str, Any]:
    """Get DLQ statistics for monitoring.
    
    Returns:
        Dict with counts by status, event_type, and other metrics
    """
    from sqlalchemy import func
    
    # Count by status
    status_stmt = (
        select(DeadLetterQueue.status, func.count())
        .group_by(DeadLetterQueue.status)
    )
    status_result = await db.execute(status_stmt)
    status_counts = {row[0]: row[1] for row in status_result.all()}
    
    # Count by event_type
    event_type_stmt = (
        select(DeadLetterQueue.event_type, func.count())
        .group_by(DeadLetterQueue.event_type)
    )
    event_type_result = await db.execute(event_type_stmt)
    event_type_counts = {row[0]: row[1] for row in event_type_result.all()}
    
    # Age analysis
    now = datetime.now(timezone.utc)
    last_hour = now - timedelta(hours=1)
    last_day = now - timedelta(days=1)
    last_week = now - timedelta(days=7)
    
    async def count_recent(since: datetime) -> int:
        stmt = select(func.count()).select_from(DeadLetterQueue).where(
            and_(
                DeadLetterQueue.failed_at >= since,
                DeadLetterQueue.status.in_(["pending", "retrying"])
            )
        )
        result = await db.execute(stmt)
        return result.scalar() or 0
    
    return {
        "total": sum(status_counts.values()),
        "by_status": status_counts,
        "by_event_type": event_type_counts,
        "pending_last_hour": await count_recent(last_hour),
        "pending_last_day": await count_recent(last_day),
        "pending_last_week": await count_recent(last_week),
    }
