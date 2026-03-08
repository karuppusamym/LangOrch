"""Dead-Letter Queue (DLQ) API endpoints."""

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.deps import require_admin, require_user
from app.db.engine import get_db, async_session
from app.schemas.dlq import (
    DLQBulkRetryRequest,
    DLQBulkRetryResponse,
    DLQMessageListOut,
    DLQMessageOut,
    DLQPurgeRequest,
    DLQPurgeResponse,
    DLQRetryResponse,
    DLQStatsOut,
)
from app.services import dlq_service

logger = logging.getLogger(__name__)

router = APIRouter()


# Default retry handler for DLQ messages
# This will be customized based on event_type
async def default_retry_handler(event_type: str, payload: dict, dlq_entry):
    """Default retry handler that dispatches to event-specific handlers."""
    if event_type == "webhook_delivery":
        # Import here to avoid circular dependency
        from app.services.case_webhook_service import deliver_webhook
        
        # Extract webhook delivery parameters from payload
        webhook_url = payload.get("webhook_url")
        event_payload = payload.get("event_payload", {})
        headers = payload.get("headers", {})
        
        if not webhook_url:
            raise ValueError("Missing webhook_url in payload")
        
        # Attempt delivery
        await deliver_webhook(webhook_url, event_payload, headers)
    
    elif event_type == "webhook_subscription_delivery":
        from app.services.case_webhook_service import _deliver_to_subscription
        
        subscription_id = payload.get("subscription_id")
        event_data = payload.get("event_data", {})
        
        if not subscription_id:
            raise ValueError("Missing subscription_id in payload")
        
        # Get DB session - use the provided db session from context
        # For DLQ retry, we need to fetch subscription in the same transaction
        async with async_session() as db:
            await _deliver_to_subscription(db, subscription_id, event_data)
    
    elif event_type == "callback_timeout":
        from app.services import run_service
        from app.worker.enqueue import requeue_run

        run_id = payload.get("run_id") or dlq_entry.entity_id
        if not run_id:
            raise ValueError("Missing run_id in callback timeout payload")

        async with async_session() as retry_db:
            run = await run_service.get_run(retry_db, run_id)
            if not run:
                raise ValueError(f"Run not found for callback timeout retry: {run_id}")

            await run_service.prepare_retry(retry_db, run_id)
            await requeue_run(retry_db, run_id, priority=10)
            await run_service.emit_event(
                retry_db,
                run_id,
                "callback_timeout_retry_requested",
                node_id=payload.get("resume_node_id"),
                step_id=payload.get("resume_step_id"),
                payload={
                    "dlq_id": dlq_entry.dlq_id,
                    "timeout_minutes": payload.get("timeout_minutes"),
                },
            )
            await retry_db.commit()
    
    else:
        logger.warning(f"Unknown event_type for retry: {event_type}")
        raise ValueError(f"No retry handler for event_type: {event_type}")


@router.get("/", response_model=DLQMessageListOut)
async def list_dlq_messages(
    event_type: str | None = Query(None, description="Filter by event type"),
    status: str | None = Query(None, description="Filter by status (pending, retrying, succeeded, exhausted, non_retriable)"),
    entity_type: str | None = Query(None, description="Filter by entity type (case, run, webhook_subscription)"),
    entity_id: str | None = Query(None, description="Filter by specific entity ID"),
    failed_after: datetime | None = Query(None, description="Messages failed after this timestamp"),
    failed_before: datetime | None = Query(None, description="Messages failed before this timestamp"),
    limit: int = Query(100, le=1000, description="Max results to return"),
    offset: int = Query(0, ge=0, description="Pagination offset"),
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
):
    """List DLQ messages with filtering and pagination.
    
    Returns failed events that can be inspected, retried, or purged.
    """
    messages = await dlq_service.get_dlq_messages(
        db,
        event_type=event_type,
        status=status,
        entity_type=entity_type,
        entity_id=entity_id,
        failed_after=failed_after,
        failed_before=failed_before,
        limit=limit,
        offset=offset,
    )
    
    total = await dlq_service.count_dlq_messages(
        db,
        event_type=event_type,
        status=status,
        entity_type=entity_type,
    )
    
    return DLQMessageListOut(
        messages=[DLQMessageOut.model_validate(msg) for msg in messages],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/stats", response_model=DLQStatsOut)
async def get_dlq_stats(
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_user),
):
    """Get DLQ statistics for monitoring.
    
    Returns counts by status, event_type, and age distribution.
    """
    stats = await dlq_service.get_dlq_stats(db)
    return DLQStatsOut(**stats)


@router.post("/{dlq_id}/retry", response_model=DLQRetryResponse)
async def retry_dlq_message(
    dlq_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Retry a single DLQ message.
    
    Attempts to re-process the failed event. If successful, message is marked
    as succeeded and removed from active DLQ. If failed and retries exhausted,
    message is marked as exhausted.
    """
    success, message = await dlq_service.retry_dlq_message(
        db,
        dlq_id,
        retry_handler=default_retry_handler,
    )
    
    return DLQRetryResponse(
        success=success,
        message=message,
        dlq_id=dlq_id,
    )


@router.post("/bulk-retry", response_model=DLQBulkRetryResponse)
async def bulk_retry_dlq(
    request: DLQBulkRetryRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Bulk retry DLQ messages with rate limiting.
    
    Retries multiple messages matching the filter criteria. Rate limiting prevents
    overwhelming downstream services. Use for mass recovery after incident resolution.
    """
    result = await dlq_service.bulk_retry_dlq(
        db,
        retry_handler=default_retry_handler,
        event_type=request.event_type,
        status=request.status,
        max_messages=request.max_messages,
        rate_limit_per_second=request.rate_limit_per_second,
    )
    
    return DLQBulkRetryResponse(**result)


@router.delete("/purge", response_model=DLQPurgeResponse)
async def purge_dlq(
    request: DLQPurgeRequest,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Purge messages from DLQ by status and age.
    
    Removes messages that have succeeded, exhausted retries, or are old.
    Use to clean up DLQ and prevent unbounded growth.
    
    At least one filter (status, purge_before_hours, event_type) must be specified.
    """
    purge_before = None
    if request.purge_before_hours:
        purge_before = datetime.now(timezone.utc) - timedelta(hours=request.purge_before_hours)
    
    try:
        purged_count = await dlq_service.purge_dlq(
            db,
            status=request.status,
            purge_before=purge_before,
            event_type=request.event_type,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    
    return DLQPurgeResponse(
        purged_count=purged_count,
        status=request.status,
        event_type=request.event_type,
    )


@router.delete("/{dlq_id}", response_model=dict)
async def delete_dlq_message(
    dlq_id: str,
    db: AsyncSession = Depends(get_db),
    _user=Depends(require_admin),
):
    """Delete a specific DLQ message by ID.
    
    Use for manual cleanup of specific messages.
    """
    from sqlalchemy import delete
    from app.db.models import DeadLetterQueue
    
    stmt = delete(DeadLetterQueue).where(DeadLetterQueue.dlq_id == dlq_id)
    result = await db.execute(stmt)
    await db.commit()
    
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail=f"DLQ message {dlq_id} not found")
    
    return {"deleted": True, "dlq_id": dlq_id}
