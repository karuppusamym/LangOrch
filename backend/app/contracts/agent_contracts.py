"""Shared capability and agent execution contracts."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Literal, Sequence

from pydantic import BaseModel, Field, field_validator

from app.contracts.action_contracts import normalize_action_name


CapabilityType = Literal["tool", "workflow"]


class AgentCapability(BaseModel):
    name: str
    type: CapabilityType = "tool"
    description: str | None = None
    estimated_duration_s: int | None = None
    is_batch: bool = False
    input_schema: dict[str, Any] | None = None
    output_schema: dict[str, Any] | None = None
    error_codes: list[str] = Field(default_factory=list)
    idempotent: bool | None = None
    side_effect_level: Literal["none", "low", "medium", "high"] | None = None
    requires_session: bool = False
    supports_async: bool = False
    auth_requirements: list[str] = Field(default_factory=list)
    platforms: list[str] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    requires_approval: bool = False
    session_scoped: bool = False

    @field_validator("name", mode="before")
    @classmethod
    def _normalize_name(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value

    @field_validator("type", mode="before")
    @classmethod
    def _normalize_type(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"tool", "workflow"}:
                return normalized
        return value


class AgentExecuteRequest(BaseModel):
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    run_id: str
    node_id: str
    step_id: str
    attempt: int = 1
    idempotency_key: str | None = None
    timeout_ms: int | None = None
    deadline_at: datetime | None = None
    trace_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    approval_id: str | None = None
    session_id: str | None = None
    lease_id: str | None = None
    callback_url: str | None = None
    dry_run: bool = False
    priority: int | None = None

    @field_validator("action", mode="before")
    @classmethod
    def _normalize_action(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip().lower()
        return value


class AgentExecuteEnvelope(BaseModel):
    status: Literal["success", "error", "accepted"]
    result: Any | None = None
    error: str | None = None
    error_code: str | None = None
    retryable: bool | None = None
    trace_id: str | None = None
    provider: str | None = None
    warnings: list[str] = Field(default_factory=list)
    metrics: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    checkpoint: dict[str, Any] | None = None
    policy: dict[str, Any] | None = None
    started_at: datetime | None = None
    ended_at: datetime | None = None
    duration_ms: int | None = None
    protocol_version: str | None = None


def parse_agent_capabilities(raw: Any) -> list[AgentCapability]:
    """Parse capabilities from JSON, CSV, ORM values, or already-typed lists."""
    if raw is None:
        return []

    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        if text.startswith("[") and text.endswith("]"):
            try:
                parsed = json.loads(text)
            except json.JSONDecodeError:
                parsed = None
            if parsed is not None:
                return parse_agent_capabilities(parsed)
        return [AgentCapability(name=item.strip()) for item in text.split(",") if item.strip()]

    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes, bytearray)):
        parsed_caps: list[AgentCapability] = []
        for item in raw:
            if isinstance(item, AgentCapability):
                parsed_caps.append(item)
            elif hasattr(item, "model_dump"):
                parsed_caps.append(AgentCapability.model_validate(item.model_dump()))
            elif isinstance(item, dict):
                parsed_caps.append(AgentCapability.model_validate(item))
            elif isinstance(item, str) and item.strip():
                parsed_caps.append(AgentCapability(name=item.strip()))
        return parsed_caps

    if hasattr(raw, "capabilities"):
        return parse_agent_capabilities(getattr(raw, "capabilities"))

    return []


def serialize_agent_capabilities(
    capabilities: Sequence[AgentCapability | dict[str, Any] | str] | None,
) -> str | None:
    """Serialize capabilities for persistence in the DB."""
    parsed = parse_agent_capabilities(capabilities)
    if not parsed:
        return None
    return json.dumps([cap.model_dump() for cap in parsed])


def capability_matches(capability_name: str, action: str) -> bool:
    """Compare capability and action names with alias normalization."""
    if capability_name == "*":
        return True
    return normalize_action_name(capability_name) == normalize_action_name(action)


def resolve_capability(capabilities: Any, action: str) -> tuple[bool, CapabilityType]:
    """Return whether the action is supported and the matched capability type."""
    parsed = parse_agent_capabilities(capabilities)
    if not parsed:
        return False, "tool"
    for cap in parsed:
        if capability_matches(cap.name, action):
            return True, cap.type
    return False, "tool"
