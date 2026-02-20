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
    provenance: dict[str, Any] | None = None
    retrieval_metadata: dict[str, Any] | None = None
    trigger: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_ckp(cls, data: Any) -> Any:
        if hasattr(data, "ckp_json") and isinstance(data.ckp_json, str):
            data.ckp_json = json.loads(data.ckp_json)
        if hasattr(data, "provenance_json") and isinstance(data.provenance_json, str):
            data.provenance = json.loads(data.provenance_json)
        elif hasattr(data, "provenance_json") and data.provenance_json is None:
            data.provenance = None
        if hasattr(data, "retrieval_metadata_json") and isinstance(data.retrieval_metadata_json, str):
            data.retrieval_metadata = json.loads(data.retrieval_metadata_json)
        elif hasattr(data, "retrieval_metadata_json") and data.retrieval_metadata_json is None:
            data.retrieval_metadata = None
        if hasattr(data, "trigger_config_json") and isinstance(data.trigger_config_json, str):
            data.trigger = json.loads(data.trigger_config_json)
        elif hasattr(data, "trigger_config_json"):
            data.trigger = None
        return data
