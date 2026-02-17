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
    started_at: datetime | None = None
    ended_at: datetime | None = None
    last_node_id: str | None = None
    last_step_id: str | None = None
    project_id: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_input_vars(cls, data: Any) -> Any:
        # Handle ORM model → dict conversion for input_vars_json
        if hasattr(data, "input_vars_json"):
            raw = data.input_vars_json
            if isinstance(raw, str):
                data.input_vars = json.loads(raw) if raw else None
            else:
                data.input_vars = raw
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
