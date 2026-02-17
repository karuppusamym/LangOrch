"""Pydantic models for procedures."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class ProcedureCreate(BaseModel):
    """Body for POST /api/procedures — the raw CKP JSON."""
    ckp_json: dict[str, Any]
    project_id: str | None = None


class ProcedureUpdate(BaseModel):
    """Body for PUT /api/procedures/{id}/{version}."""
    ckp_json: dict[str, Any]


class ProcedureOut(BaseModel):
    id: int
    procedure_id: str
    version: str
    name: str
    status: str
    effective_date: str | None = None
    description: str | None = None
    project_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProcedureDetail(ProcedureOut):
    ckp_json: dict[str, Any]

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_ckp(cls, data: Any) -> Any:
        if hasattr(data, "ckp_json") and isinstance(data.ckp_json, str):
            data.ckp_json = json.loads(data.ckp_json)
        return data
