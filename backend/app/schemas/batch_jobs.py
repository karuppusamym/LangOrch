"""Pydantic models for batch job submission and monitoring."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class BatchJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=256)
    procedure_id: str
    procedure_version: str | None = None
    source_format: Literal["json", "jsonl", "csv"] = "json"
    payload_text: str = Field(min_length=1)
    project_id: str | None = None
    create_case_per_item: bool = False
    case_type: str | None = None
    title_field: str | None = None
    external_ref_field: str | None = None
    tags: list[str] | None = None


class BatchJobOut(BaseModel):
    batch_job_id: str
    name: str
    procedure_id: str
    procedure_version: str
    status: str
    source_format: str
    total_items: int
    queued_items: int = 0
    running_items: int = 0
    completed_items: int = 0
    failed_items: int = 0
    canceled_items: int = 0
    create_case_per_item: bool
    case_type: str | None = None
    trigger_type: str | None = None
    triggered_by: str | None = None
    project_id: str | None = None
    created_at: datetime
    updated_at: datetime
    completed_at: datetime | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if hasattr(data, "__dict__") and hasattr(data, "batch_job_id"):
            return {
                "batch_job_id": data.batch_job_id,
                "name": data.name,
                "procedure_id": data.procedure_id,
                "procedure_version": data.procedure_version,
                "status": data.status,
                "source_format": data.source_format,
                "total_items": data.total_items,
                "queued_items": getattr(data, "queued_items", 0),
                "running_items": getattr(data, "running_items", 0),
                "completed_items": getattr(data, "completed_items", 0),
                "failed_items": getattr(data, "failed_items", 0),
                "canceled_items": getattr(data, "canceled_items", 0),
                "create_case_per_item": data.create_case_per_item,
                "case_type": data.case_type,
                "trigger_type": data.trigger_type,
                "triggered_by": data.triggered_by,
                "project_id": data.project_id,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
                "completed_at": data.completed_at,
            }
        return data


class BatchJobItemOut(BaseModel):
    item_id: str
    batch_job_id: str
    item_index: int
    status: str
    input_vars: dict[str, Any] | None = None
    run_id: str | None = None
    case_id: str | None = None
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _normalize(cls, data: Any) -> Any:
        if hasattr(data, "__dict__") and hasattr(data, "item_id"):
            return {
                "item_id": data.item_id,
                "batch_job_id": data.batch_job_id,
                "item_index": data.item_index,
                "status": data.status,
                "input_vars": json.loads(data.input_vars_json) if getattr(data, "input_vars_json", None) else None,
                "run_id": data.run_id,
                "case_id": data.case_id,
                "error_message": data.error_message,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
        if isinstance(data, dict) and "input_vars_json" in data and "input_vars" not in data:
            raw = data.get("input_vars_json")
            data["input_vars"] = json.loads(raw) if isinstance(raw, str) and raw else None
        return data


class BatchJobOperationResult(BaseModel):
    batch_job_id: str
    affected: int
    item_ids: list[str] = Field(default_factory=list)
