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

    @staticmethod
    def _decode_payload(raw: Any) -> dict[str, Any] | None:
        if isinstance(raw, str):
            try:
                return json.loads(raw)
            except Exception:
                return None
        return raw

    @model_validator(mode="before")
    @classmethod
    def _parse_payload(cls, data: Any) -> Any:
        if isinstance(data, dict):
            parsed = dict(data)
            if "payload" not in parsed and "payload_json" in parsed:
                parsed["payload"] = cls._decode_payload(parsed.get("payload_json"))
            return parsed

        if hasattr(data, "event_id"):
            return {
                "event_id": data.event_id,
                "run_id": data.run_id,
                "created_at": data.ts,
                "event_type": data.event_type,
                "node_id": data.node_id,
                "step_id": data.step_id,
                "attempt": data.attempt,
                "payload": cls._decode_payload(getattr(data, "payload_json", None)),
            }

        return data
