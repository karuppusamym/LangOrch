"""Pydantic models for trigger registrations."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, field_validator, model_validator


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
    trigger_type: Literal["scheduled", "webhook", "event", "file_watch"]
    schedule: str | None = None
    webhook_secret: str | None = None
    event_source: str | None = None
    dedupe_window_seconds: int = 0
    max_concurrent_runs: int | None = None
    enabled: bool = True

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: str | None) -> str | None:
        if value is None:
            return value
        parts = value.strip().split()
        if len(parts) != 5:
            raise ValueError("Cron schedule must use exactly 5 fields in UTC")
        from apscheduler.triggers.cron import CronTrigger  # type: ignore[import]

        CronTrigger.from_crontab(value, timezone="UTC")
        return value.strip()

    @field_validator("dedupe_window_seconds")
    @classmethod
    def validate_dedupe_window(cls, value: int) -> int:
        if value < 0:
            raise ValueError("dedupe_window_seconds must be >= 0")
        return value

    @field_validator("max_concurrent_runs")
    @classmethod
    def validate_max_concurrent_runs(cls, value: int | None) -> int | None:
        if value is not None and value < 1:
            raise ValueError("max_concurrent_runs must be >= 1")
        return value

    @model_validator(mode="after")
    def validate_trigger_requirements(self) -> "TriggerRegistrationCreate":
        if self.trigger_type == "scheduled" and not self.schedule:
            raise ValueError("scheduled triggers require a cron schedule")
        if self.trigger_type == "webhook" and not self.webhook_secret:
            raise ValueError("webhook triggers require webhook_secret")
        if self.trigger_type in {"event", "file_watch"} and not self.event_source:
            raise ValueError(f"{self.trigger_type} triggers require event_source")
        return self


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
