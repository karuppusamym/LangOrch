"""Pydantic models for runs."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class RunCreate(BaseModel):
    procedure_id: str
    procedure_version: str | None = None
    input_vars: dict[str, Any] | None = None
    project_id: str | None = None


class RunOut(BaseModel):
    run_id: str
    procedure_id: str
    procedure_version: str
    thread_id: str
    status: str
    input_vars: dict[str, Any] | None = None
    output_vars: dict[str, Any] | None = None
    total_prompt_tokens: int | None = None
    total_completion_tokens: int | None = None
    estimated_cost_usd: float | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_seconds: float | None = None
    last_node_id: str | None = None
    last_step_id: str | None = None
    error_message: str | None = None
    parent_run_id: str | None = None
    trigger_type: str | None = None
    triggered_by: str | None = None
    project_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_fields(cls, data: Any) -> Any:
        # When coming from ORM → build a plain dict to avoid mutating the ORM object
        if hasattr(data, "__dict__") and hasattr(data, "run_id"):
            d: dict[str, Any] = {
                "run_id": data.run_id,
                "procedure_id": data.procedure_id,
                "procedure_version": data.procedure_version,
                "thread_id": data.thread_id,
                "status": data.status,
                "started_at": data.started_at,
                "ended_at": data.ended_at,
                "last_node_id": data.last_node_id,
                "last_step_id": data.last_step_id,
                "error_message": data.error_message if hasattr(data, "error_message") else None,
                "parent_run_id": data.parent_run_id if hasattr(data, "parent_run_id") else None,
                "trigger_type": getattr(data, "trigger_type", None),
                "triggered_by": getattr(data, "triggered_by", None),
                "project_id": data.project_id,
                "created_at": data.created_at,
                "updated_at": data.updated_at,
            }
            # Parse input_vars / output_vars from JSON string
            raw = data.input_vars_json
            d["input_vars"] = json.loads(raw) if isinstance(raw, str) and raw else raw
            raw_out = getattr(data, "output_vars_json", None)
            d["output_vars"] = json.loads(raw_out) if isinstance(raw_out, str) and raw_out else None
            d["total_prompt_tokens"] = getattr(data, "total_prompt_tokens", None)
            d["total_completion_tokens"] = getattr(data, "total_completion_tokens", None)
            d["estimated_cost_usd"] = getattr(data, "estimated_cost_usd", None)
            # Compute duration
            if d["started_at"] and d["ended_at"]:
                d["duration_seconds"] = (d["ended_at"] - d["started_at"]).total_seconds()
            return d
        # Plain dict path
        if isinstance(data, dict):
            if "input_vars_json" in data and "input_vars" not in data:
                raw = data.get("input_vars_json")
                data["input_vars"] = json.loads(raw) if isinstance(raw, str) and raw else raw
            if "output_vars_json" in data and "output_vars" not in data:
                raw_out = data.get("output_vars_json")
                data["output_vars"] = json.loads(raw_out) if isinstance(raw_out, str) and raw_out else None
            if data.get("started_at") and data.get("ended_at") and "duration_seconds" not in data:
                data["duration_seconds"] = (data["ended_at"] - data["started_at"]).total_seconds()
        return data


class ArtifactOut(BaseModel):
    artifact_id: str
    run_id: str
    node_id: str | None = None
    step_id: str | None = None
    kind: str
    uri: str
    created_at: datetime

    model_config = {"from_attributes": True}


class StepIdempotencyDiagnostic(BaseModel):
    node_id: str
    step_id: str
    idempotency_key: str | None
    status: str
    has_cached_result: bool
    updated_at: datetime


class ResourceLeaseDiagnostic(BaseModel):
    lease_id: str
    resource_key: str
    node_id: str | None
    step_id: str | None
    acquired_at: datetime
    expires_at: datetime
    released_at: datetime | None
    is_active: bool


class RunDiagnostics(BaseModel):
    run_id: str
    thread_id: str
    status: str
    last_node_id: str | None
    last_step_id: str | None
    has_retry_event: bool
    idempotency_entries: list[StepIdempotencyDiagnostic]
    active_leases: list[ResourceLeaseDiagnostic]
    total_events: int
    error_events: int

class CheckpointMetadata(BaseModel):
    """Metadata for a single checkpoint in the execution timeline."""
    checkpoint_id: str | None
    thread_id: str
    parent_checkpoint_id: str | None
    step: int
    writes: Any | None
    created_at: str


class CheckpointState(BaseModel):
    """Full state snapshot at a checkpoint."""
    checkpoint_id: str | None
    thread_id: str
    channel_values: dict[str, Any]
    metadata: dict[str, Any]
    pending_writes: list[Any]
    versions_seen: dict[str, Any]