"""Pydantic models for trigger registrations."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class TriggerRegistrationOut(BaseModel):
    id: int
    procedure_id: str
    version: str
    trigger_type: str
    schedule: str | None = None
    webhook_secret: str | None = None
    event_source: str | None = None
    dedupe_window_seconds: int = 0
    max_concurrent_runs: int | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class TriggerRegistrationCreate(BaseModel):
    """Manually register or override a trigger for a procedure version."""
    trigger_type: str  # scheduled | webhook | event | file_watch
    schedule: str | None = None
    webhook_secret: str | None = None
    event_source: str | None = None
    dedupe_window_seconds: int = 0
    max_concurrent_runs: int | None = None
    enabled: bool = True


class WebhookFireOut(BaseModel):
    """Returned when a webhook fires successfully."""
    run_id: str
    procedure_id: str
    procedure_version: str
    trigger_type: str = "webhook"
    status: str = "created"


class TriggerFireOut(BaseModel):
    """Returned when a trigger fires (any type)."""
    run_id: str
    procedure_id: str
    procedure_version: str
    trigger_type: str
    triggered_by: str | None = None
    status: str = "created"
