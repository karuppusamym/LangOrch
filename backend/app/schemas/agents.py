"""Pydantic models for agent instances."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class AgentInstanceCreate(BaseModel):
    agent_id: str | None = None
    name: str
    channel: str
    base_url: str
    concurrency_limit: int = 1
    resource_key: str | None = None
    capabilities: list[str] | None = None


class AgentInstanceUpdate(BaseModel):
    """Body for PUT /api/agents/{id} — all fields optional."""
    status: str | None = None
    base_url: str | None = None
    concurrency_limit: int | None = None
    capabilities: list[str] | None = None


class AgentInstanceOut(BaseModel):
    agent_id: str
    name: str
    channel: str
    base_url: str
    status: str
    concurrency_limit: int
    resource_key: str
    capabilities: list[str] = []
    consecutive_failures: int = 0
    circuit_open_at: datetime | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_capabilities(cls, data: Any) -> Any:
        # data may be an ORM object or a plain dict
        if isinstance(data, dict):
            parsed = dict(data)
            raw = parsed.get("capabilities")
            if isinstance(raw, str):
                parsed["capabilities"] = [c.strip() for c in raw.split(",") if c.strip()]
            elif raw is None:
                parsed["capabilities"] = []
            return parsed

        if hasattr(data, "capabilities"):
            raw = data.capabilities
            if isinstance(raw, str):
                parsed_caps = [c.strip() for c in raw.split(",") if c.strip()]
            elif raw is None:
                parsed_caps = []
            else:
                parsed_caps = raw

            return {
                "agent_id": data.agent_id,
                "name": data.name,
                "channel": data.channel,
                "base_url": data.base_url,
                "status": data.status,
                "concurrency_limit": data.concurrency_limit,
                "resource_key": data.resource_key,
                "capabilities": parsed_caps,
                "consecutive_failures": getattr(data, "consecutive_failures", 0) or 0,
                "circuit_open_at": getattr(data, "circuit_open_at", None),
                "updated_at": data.updated_at,
            }

        return data
