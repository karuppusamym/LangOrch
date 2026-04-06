"""Pydantic models for agent instances."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.config import settings
from app.contracts.agent_contracts import AgentCapability, parse_agent_capabilities

class AgentInstanceCreate(BaseModel):
    agent_id: str | None = None
    name: str
    channel: str
    base_url: str
    concurrency_limit: int = 1
    resource_key: str | None = None
    capabilities: list[AgentCapability] | None = None
    pool_id: str | None = None
    """Optional pool name for round-robin dispatch across multiple agents."""


class AgentInstanceUpdate(BaseModel):
    """Body for PUT /api/agents/{id} — all fields optional."""
    status: str | None = None
    base_url: str | None = None
    concurrency_limit: int | None = None
    capabilities: list[AgentCapability] | None = None
    pool_id: str | None = None


class AgentHeartbeat(BaseModel):
    agent_id: str
    status: str = "online"
    cpu_percent: float | None = None
    memory_percent: float | None = None


class AgentBootstrapOut(BaseModel):
    channel: str
    default_pool: str
    recommended_concurrency: int


class AgentInstanceOut(BaseModel):
    agent_id: str
    name: str
    channel: str
    base_url: str
    status: str
    concurrency_limit: int
    resource_key: str
    pool_id: str | None = None
    capabilities: list[AgentCapability] = []
    consecutive_failures: int = 0
    circuit_open_at: datetime | None = None
    last_heartbeat_at: datetime | None = None
    heartbeat_age_seconds: int | None = None
    is_stale: bool = False
    protocol_version: str | None = None
    supports_sessions: bool = False
    capability_contract_coverage: float = 0.0
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_capabilities(cls, data: Any) -> Any:
        # data may be an ORM object or a plain dict
        if isinstance(data, dict):
            parsed = dict(data)
            caps = parse_agent_capabilities(parsed.get("capabilities"))
            parsed["capabilities"] = [cap.model_dump() for cap in caps]
            heartbeat_at = parsed.get("last_heartbeat_at")
            if isinstance(heartbeat_at, datetime):
                if heartbeat_at.tzinfo is None:
                    heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
                parsed["heartbeat_age_seconds"] = max(0, int((datetime.now(timezone.utc) - heartbeat_at).total_seconds()))
            else:
                parsed["heartbeat_age_seconds"] = None
            parsed["is_stale"] = (
                parsed["heartbeat_age_seconds"] is not None
                and parsed["heartbeat_age_seconds"] >= settings.AGENT_STALE_AFTER_SECONDS
            )
            parsed["protocol_version"] = settings.AGENT_PROTOCOL_VERSION
            parsed["supports_sessions"] = any(cap.session_scoped or cap.requires_session or cap.name in {"open_session", "resume_session", "close_session"} for cap in caps)
            total_caps = len(caps)
            contract_caps = sum(1 for cap in caps if cap.input_schema and cap.output_schema)
            parsed["capability_contract_coverage"] = round((contract_caps / total_caps), 3) if total_caps else 0.0
            return parsed

        if hasattr(data, "capabilities"):
            caps = parse_agent_capabilities(data.capabilities)
            parsed_caps = [cap.model_dump() for cap in caps]
            heartbeat_at = getattr(data, "last_heartbeat_at", None)
            heartbeat_age_seconds: int | None = None
            if isinstance(heartbeat_at, datetime):
                if heartbeat_at.tzinfo is None:
                    heartbeat_at = heartbeat_at.replace(tzinfo=timezone.utc)
                heartbeat_age_seconds = max(0, int((datetime.now(timezone.utc) - heartbeat_at).total_seconds()))
            total_caps = len(caps)
            contract_caps = sum(1 for cap in caps if cap.input_schema and cap.output_schema)

            return {
                "agent_id": data.agent_id,
                "name": data.name,
                "channel": data.channel,
                "base_url": data.base_url,
                "status": data.status,
                "concurrency_limit": data.concurrency_limit,
                "resource_key": data.resource_key,
                "pool_id": getattr(data, "pool_id", None),
                "capabilities": parsed_caps,
                "consecutive_failures": getattr(data, "consecutive_failures", 0) or 0,
                "circuit_open_at": getattr(data, "circuit_open_at", None),
                "last_heartbeat_at": getattr(data, "last_heartbeat_at", None),
                "heartbeat_age_seconds": heartbeat_age_seconds,
                "is_stale": heartbeat_age_seconds is not None and heartbeat_age_seconds >= settings.AGENT_STALE_AFTER_SECONDS,
                "protocol_version": settings.AGENT_PROTOCOL_VERSION,
                "supports_sessions": any(cap.session_scoped or cap.requires_session or cap.name in {"open_session", "resume_session", "close_session"} for cap in caps),
                "capability_contract_coverage": round((contract_caps / total_caps), 3) if total_caps else 0.0,
                "updated_at": data.updated_at,
            }

        return data


class AgentContractTestRequest(BaseModel):
    mode: Literal["simulate", "replay"] = "simulate"
    capabilities: list[str] | None = None


class AgentContractResult(BaseModel):
    capability: str
    capability_type: Literal["tool", "workflow"]
    mode: Literal["simulate", "replay"]
    status: Literal["passed", "failed", "skipped"]
    request: dict[str, Any] | None = None
    response: dict[str, Any] | None = None
    error: str | None = None


class AgentContractTestOut(BaseModel):
    agent_id: str
    mode: Literal["simulate", "replay"]
    total: int
    passed: int
    failed: int
    skipped: int
    results: list[AgentContractResult] = Field(default_factory=list)
