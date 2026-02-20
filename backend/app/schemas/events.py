"""Pydantic models for run events."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator, Field


class RunEventOut(BaseModel):
    event_id: int
    run_id: str
    # validation_alias reads the ORM "ts" column but serialises as "created_at"
    created_at: datetime = Field(validation_alias="ts")
    event_type: str
    node_id: str | None = None
    step_id: str | None = None
    attempt: int | None = None
    payload: dict[str, Any] | None = None

    model_config = {"from_attributes": True, "populate_by_name": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_payload(cls, data: Any) -> Any:
        if hasattr(data, "payload_json"):
            raw = data.payload_json
            if isinstance(raw, str):
                try:
                    data.payload = json.loads(raw)
                except Exception:
                    data.payload = None
            else:
                data.payload = raw
        return data
