"""Pydantic models for case-centric orchestration."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class CaseCreate(BaseModel):
    title: str = Field(min_length=1, max_length=256)
    project_id: str | None = None
    external_ref: str | None = None
    case_type: str | None = None
    description: str | None = None
    status: str = "open"
    priority: str = "normal"
    owner: str | None = None
    sla_due_at: datetime | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=256)
    external_ref: str | None = None
    case_type: str | None = None
    description: str | None = None
    status: str | None = None
    priority: str | None = None
    owner: str | None = None
    sla_due_at: datetime | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None


class CaseOut(BaseModel):
    case_id: str
    project_id: str | None = None
    external_ref: str | None = None
    case_type: str | None = None
    title: str
    description: str | None = None
    status: str
    priority: str
    owner: str | None = None
    sla_due_at: datetime | None = None
    sla_breached_at: datetime | None = None
    tags: list[str] | None = None
    metadata: dict[str, Any] | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_fields(cls, data: Any) -> Any:
        if hasattr(data, "__dict__") and hasattr(data, "case_id"):
            return {
                "case_id": data.case_id,
                "project_id": data.project_id,
                "external_ref": data.external_ref,
                "case_type": data.case_type,
                "title": data.title,
                "description": data.description,
                "status": data.status,
                "priority": data.priority,
                "owner": data.owner,
                "sla_due_at": data.sla_due_at,
                "sla_breached_at": data.sla_breached_at,
                "tags": json.loads(data.tags_json) if data.tags_json else None,
                "metadata": json.loads(data.metadata_json) if data.metadata_json else None,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        if isinstance(data, dict):
            if "tags_json" in data and "tags" not in data:
                raw_tags = data.get("tags_json")
                data["tags"] = json.loads(raw_tags) if isinstance(raw_tags, str) and raw_tags else None
            if "metadata_json" in data and "metadata" not in data:
                raw_meta = data.get("metadata_json")
                data["metadata"] = json.loads(raw_meta) if isinstance(raw_meta, str) and raw_meta else None
        return data


class CaseEventOut(BaseModel):
    event_id: int
    case_id: str
    ts: datetime
    event_type: str
    actor: str | None = None
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_fields(cls, data: Any) -> Any:
        if hasattr(data, "__dict__") and hasattr(data, "event_id"):
            return {
                "event_id": data.event_id,
                "case_id": data.case_id,
                "ts": data.ts,
                "event_type": data.event_type,
                "actor": data.actor,
                "payload": json.loads(data.payload_json) if data.payload_json else None,
            }
        if isinstance(data, dict) and "payload_json" in data and "payload" not in data:
            raw = data.get("payload_json")
            data["payload"] = json.loads(raw) if isinstance(raw, str) and raw else None
        return data


class CaseQueueItemOut(CaseOut):
    priority_rank: int
    age_seconds: float
    sla_remaining_seconds: float | None = None
    is_sla_breached: bool


class CaseQueueAnalyticsOut(BaseModel):
    total_active_cases: int
    unassigned_cases: int
    breached_cases: int
    breach_risk_next_window_cases: int
    breach_risk_next_window_percent: float
    wait_p50_seconds: float
    wait_p95_seconds: float
    wait_by_priority: dict[str, dict[str, float | int]]
    wait_by_case_type: dict[str, dict[str, float | int]]
    reassignment_rate_24h: float
    abandonment_rate_24h: float


class CaseClaimRequest(BaseModel):
    owner: str = Field(min_length=1, max_length=256)
    set_in_progress: bool = True


class CaseReleaseRequest(BaseModel):
    owner: str | None = None
    set_open: bool = False


class CaseWebhookSubscriptionCreate(BaseModel):
    event_type: str = "*"
    target_url: str = Field(min_length=1)
    project_id: str | None = None
    secret_env_var: str | None = None
    enabled: bool = True


class CaseWebhookSubscriptionOut(BaseModel):
    subscription_id: str
    event_type: str
    target_url: str
    project_id: str | None = None
    secret_env_var: str | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseWebhookDeliveryOut(BaseModel):
    delivery_id: str
    subscription_id: str
    case_event_id: int | None = None
    case_id: str | None = None
    project_id: str | None = None
    event_type: str
    status: str
    attempts: int
    max_attempts: int
    next_attempt_at: datetime
    last_status_code: int | None = None
    last_error: str | None = None
    delivered_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class CaseWebhookReplayOut(BaseModel):
    replayed: int
    delivery_ids: list[str] = Field(default_factory=list)
    skipped_non_failed_ids: list[str] = Field(default_factory=list)
    not_found_ids: list[str] = Field(default_factory=list)


class CaseWebhookReplaySelectedIn(BaseModel):
    delivery_ids: list[str] = Field(min_length=1, max_length=500)


class CaseWebhookDeliverySummaryOut(BaseModel):
    total: int
    by_status: dict[str, int]
    oldest_pending_age_seconds: float | None = None
    recent_failures_last_hour: int


class CaseWebhookDeliveryCountOut(BaseModel):
    total: int


class CaseWebhookPurgeOut(BaseModel):
    deleted: int


class CaseWebhookPurgeSelectedIn(BaseModel):
    delivery_ids: list[str] = Field(min_length=1, max_length=500)


class CaseWebhookPurgeSelectedOut(BaseModel):
    deleted: int
    delivery_ids: list[str] = Field(default_factory=list)
    skipped_non_failed_ids: list[str] = Field(default_factory=list)
    not_found_ids: list[str] = Field(default_factory=list)


class CaseSlaPolicyCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    project_id: str | None = None
    case_type: str | None = None
    priority: str | None = None
    due_minutes: int = Field(ge=1, le=60 * 24 * 30)
    breach_status: str = "escalated"
    enabled: bool = True


class CaseSlaPolicyUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=256)
    case_type: str | None = None
    priority: str | None = None
    due_minutes: int | None = Field(default=None, ge=1, le=60 * 24 * 30)
    breach_status: str | None = None
    enabled: bool | None = None


class CaseSlaPolicyOut(BaseModel):
    policy_id: str
    name: str
    project_id: str | None = None
    case_type: str | None = None
    priority: str | None = None
    due_minutes: int
    breach_status: str
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
