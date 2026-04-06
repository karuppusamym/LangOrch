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
    dispatch_mode: str = "run"
    static_payload: Any | None = None
    case_type: str | None = None
    case_title_template: str | None = None
    case_external_ref_field: str | None = None
    create_case_tags: list[str] | None = None
    enabled: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if hasattr(data, "__dict__") and hasattr(data, "procedure_id"):
            import json as _json

            return {
                "id": data.id,
                "procedure_id": data.procedure_id,
                "version": data.version,
                "trigger_type": data.trigger_type,
                "schedule": data.schedule,
                "webhook_secret": data.webhook_secret,
                "event_source": data.event_source,
                "dedupe_window_seconds": data.dedupe_window_seconds,
                "max_concurrent_runs": data.max_concurrent_runs,
                "dispatch_mode": getattr(data, "dispatch_mode", "run"),
                "static_payload": _json.loads(data.static_payload_json) if getattr(data, "static_payload_json", None) else None,
                "case_type": getattr(data, "case_type", None),
                "case_title_template": getattr(data, "case_title_template", None),
                "case_external_ref_field": getattr(data, "case_external_ref_field", None),
                "create_case_tags": _json.loads(data.create_case_tags_json) if getattr(data, "create_case_tags_json", None) else None,
                "enabled": data.enabled,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        return data


class TriggerRegistrationCreate(BaseModel):
    """Manually register or override a trigger for a procedure version."""
    trigger_type: Literal["scheduled", "webhook", "event", "file_watch"]
    schedule: str | None = None
    webhook_secret: str | None = None
    event_source: str | None = None
    dedupe_window_seconds: int = 0
    max_concurrent_runs: int | None = None
    dispatch_mode: Literal["run", "batch", "case_run"] = "run"
    static_payload: Any | None = None
    case_type: str | None = None
    case_title_template: str | None = None
    case_external_ref_field: str | None = None
    create_case_tags: list[str] | None = None
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
        if self.dispatch_mode == "case_run" and not (self.case_type and self.case_type.strip()):
            raise ValueError("case_run dispatch requires case_type")
        return self


class WebhookFireOut(BaseModel):
    """Returned when a webhook fires successfully."""
    entity_type: Literal["run", "batch_job", "case_run"] = "run"
    run_id: str | None = None
    batch_job_id: str | None = None
    case_id: str | None = None
    procedure_id: str
    procedure_version: str
    trigger_type: str = "webhook"
    status: str = "created"


class TriggerFireOut(BaseModel):
    """Returned when a trigger fires (any type)."""
    entity_type: Literal["run", "batch_job", "case_run"] = "run"
    run_id: str | None = None
    batch_job_id: str | None = None
    case_id: str | None = None
    procedure_id: str
    procedure_version: str
    trigger_type: str
    triggered_by: str | None = None
    status: str = "created"
