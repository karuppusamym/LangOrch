"""Pydantic models for approvals."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class ApprovalOut(BaseModel):
    approval_id: str
    run_id: str
    node_id: str
    prompt: str
    decision_type: str
    options_json: Any | None = None
    context_data_json: Any | None = None
    status: str
    decided_by: str | None = None
    decision_json: Any | None = None
    created_at: datetime
    decided_at: datetime | None = None

    model_config = {"from_attributes": True}


class ApprovalDecision(BaseModel):
    status: str | None = None  # approved | rejected
    decision: str | None = None  # approve | reject | option value
    decided_by: str | None = None
    comment: str | None = None
    payload: dict[str, Any] | None = None

    @property
    def resolved_decision(self) -> str:
        return self.status or self.decision or "rejected"
