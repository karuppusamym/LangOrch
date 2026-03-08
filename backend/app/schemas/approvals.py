"""Pydantic models for approvals."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator


class ApprovalOut(BaseModel):
    approval_id: str
    run_id: str
    node_id: str
    prompt: str
    decision_type: str
    options: list[str] | None = None
    context_data: dict[str, Any] | None = None
    status: str
    decided_by: str | None = None
    decision_payload: dict[str, Any] | None = None
    comment: str | None = None
    created_at: datetime
    decided_at: datetime | None = None
    expires_at: datetime | None = None
    run_status: str | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_fields(cls, data: Any) -> Any:
        def _decode(value: Any) -> Any:
            if isinstance(value, str):
                try:
                    return json.loads(value)
                except (TypeError, ValueError):
                    return None
            return value

        def _build(values: dict[str, Any]) -> dict[str, Any]:
            decision_payload = _decode(values.get("decision_json") or values.get("decision_payload"))
            comment = None
            if isinstance(decision_payload, dict):
                raw_comment = decision_payload.get("comment")
                if raw_comment is not None:
                    comment = str(raw_comment)
            return {
                "approval_id": values.get("approval_id"),
                "run_id": values.get("run_id"),
                "node_id": values.get("node_id"),
                "prompt": values.get("prompt"),
                "decision_type": values.get("decision_type"),
                "options": _decode(values.get("options_json") or values.get("options")),
                "context_data": _decode(values.get("context_data_json") or values.get("context_data")),
                "status": values.get("status"),
                "decided_by": values.get("decided_by"),
                "decision_payload": decision_payload,
                "comment": comment,
                "created_at": values.get("created_at"),
                "decided_at": values.get("decided_at"),
                "expires_at": values.get("expires_at"),
                "run_status": values.get("run_status"),
            }

        if hasattr(data, "approval_id"):
            return _build(
                {
                    "approval_id": data.approval_id,
                    "run_id": data.run_id,
                    "node_id": data.node_id,
                    "prompt": data.prompt,
                    "decision_type": data.decision_type,
                    "options_json": getattr(data, "options_json", None),
                    "context_data_json": getattr(data, "context_data_json", None),
                    "status": data.status,
                    "decided_by": getattr(data, "decided_by", None),
                    "decision_json": getattr(data, "decision_json", None),
                    "created_at": data.created_at,
                    "decided_at": getattr(data, "decided_at", None),
                    "expires_at": getattr(data, "expires_at", None),
                    "run_status": getattr(data, "run_status", None),
                }
            )
        if isinstance(data, dict):
            return _build(data)
        return data


class ApprovalDecision(BaseModel):
    status: str | None = None  # approved | rejected
    decision: str | None = None  # approve | reject | option value
    resolved_decision_value: str | None = Field(default=None, alias="resolved_decision")
    decided_by: str | None = None
    comment: str | None = None
    payload: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    @property
    def resolved_decision(self) -> str:
        value = self.status or self.decision or self.resolved_decision_value or "rejected"
        if value == "approve":
            return "approved"
        if value == "reject":
            return "rejected"
        return value
