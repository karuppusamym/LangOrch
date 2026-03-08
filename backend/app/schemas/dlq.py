"""Pydantic schemas for Dead-Letter Queue (DLQ) API."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class DLQMessageOut(BaseModel):
    """DLQ message response schema."""

    model_config = {"from_attributes": True}
    
    dlq_id: str
    event_type: str
    entity_type: str | None = None
    entity_id: str | None = None
    payload_json: str  # JSON string
    original_timestamp: datetime
    failed_at: datetime
    last_retry_at: datetime | None = None
    succeeded_at: datetime | None = None
    error_message: str | None = None
    error_type: str | None = None
    http_status_code: int | None = None
    retry_count: int
    max_retries: int
    status: str  # pending | retrying | succeeded | exhausted | non_retriable
    metadata_json: str | None = None
    created_by: str | None = None
    updated_at: datetime


class DLQMessageListOut(BaseModel):
    """Paginated list of DLQ messages."""
    
    messages: list[DLQMessageOut]
    total: int
    limit: int
    offset: int


class DLQRetryRequest(BaseModel):
    """Request to retry a single DLQ message."""
    
    dlq_id: str


class DLQBulkRetryRequest(BaseModel):
    """Request for bulk retry of DLQ messages."""
    
    event_type: str | None = None
    status: str | None = Field(default="pending", description="Filter by status")
    max_messages: int = Field(default=100, le=1000, description="Max messages to retry")
    rate_limit_per_second: int = Field(default=10, ge=1, le=100, description="Max retry rate")


class DLQBulkRetryResponse(BaseModel):
    """Response from bulk retry operation."""
    
    success_count: int
    failed_count: int
    skipped_count: int
    total_processed: int
    errors: list[dict[str, Any]] = []


class DLQPurgeRequest(BaseModel):
    """Request to purge messages from DLQ."""
    
    status: str | None = Field(default=None, description="Purge messages with this status (succeeded, exhausted, etc.)")
    purge_before_hours: int | None = Field(default=None, ge=1, description="Purge messages older than this many hours")
    event_type: str | None = Field(default=None, description="Filter by event type")


class DLQPurgeResponse(BaseModel):
    """Response from purge operation."""
    
    purged_count: int
    status: str | None = None
    event_type: str | None = None


class DLQStatsOut(BaseModel):
    """DLQ statistics for monitoring."""
    
    total: int
    by_status: dict[str, int]
    by_event_type: dict[str, int]
    pending_last_hour: int
    pending_last_day: int
    pending_last_week: int


class DLQRetryResponse(BaseModel):
    """Response from single message retry."""
    
    success: bool
    message: str
    dlq_id: str
