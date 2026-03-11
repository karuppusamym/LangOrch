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


class ProcedureBuilderDraftUpdate(BaseModel):
    """Body for PUT /api/procedures/{id}/{version}/builder-draft."""

    draft: dict[str, Any]


class ProcedureOut(BaseModel):
    id: int
    procedure_id: str
    version: str
    name: str
    status: str
    effective_date: str | None = None
    description: str | None = None
    release_channel: str | None = None
    promoted_from_version: str | None = None
    promoted_at: datetime | None = None
    promoted_by: str | None = None
    project_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class ProcedureDetail(ProcedureOut):
    ckp_json: dict[str, Any]
    builder_draft: dict[str, Any] | None = None
    builder_draft_updated_at: datetime | None = None
    provenance: dict[str, Any] | None = None
    retrieval_metadata: dict[str, Any] | None = None
    trigger: dict[str, Any] | None = None

    model_config = {"from_attributes": True}

    @staticmethod
    def _parse_json_field(value: Any) -> dict[str, Any] | None:
        if value is None:
            return None
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return json.loads(value)
        return value

    @model_validator(mode="before")
    @classmethod
    def _parse_ckp(cls, data: Any) -> Any:
        if isinstance(data, dict):
            payload = dict(data)
        else:
            payload = {
                field_name: getattr(data, field_name)
                for field_name in ProcedureOut.model_fields
                if hasattr(data, field_name)
            }
            if hasattr(data, "builder_draft_updated_at"):
                payload["builder_draft_updated_at"] = data.builder_draft_updated_at

        payload["ckp_json"] = cls._parse_json_field(payload.get("ckp_json", getattr(data, "ckp_json", None))) or {}
        payload["builder_draft"] = cls._parse_json_field(
            payload.get("builder_draft", payload.get("builder_draft_json", getattr(data, "builder_draft_json", None)))
        )
        payload["provenance"] = cls._parse_json_field(
            payload.get("provenance", payload.get("provenance_json", getattr(data, "provenance_json", None)))
        )
        payload["retrieval_metadata"] = cls._parse_json_field(
            payload.get(
                "retrieval_metadata",
                payload.get("retrieval_metadata_json", getattr(data, "retrieval_metadata_json", None)),
            )
        )
        payload["trigger"] = cls._parse_json_field(
            payload.get("trigger", payload.get("trigger_config_json", getattr(data, "trigger_config_json", None)))
        )
        return payload


class ProcedureBuilderDraftOut(BaseModel):
    procedure_id: str
    version: str
    draft: dict[str, Any] | None = None
    updated_at: datetime | None = None


class ProcedurePromoteRequest(BaseModel):
    """Body for POST /api/procedures/{id}/{version}/promote."""

    target_channel: str


class ProcedurePromoteResponse(BaseModel):
    """Response for procedure promotion operations."""

    promoted: ProcedureOut
    previous_channel_version: str | None = None


class ProcedureRollbackRequest(BaseModel):
    """Body for POST /api/procedures/{id}/{version}/rollback."""

    target_channel: str
    rollback_to_version: str | None = None


class ProcedureRollbackResponse(BaseModel):
    """Response for procedure rollback operations."""

    restored: ProcedureOut
    replaced_version: str
