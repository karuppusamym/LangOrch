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
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_capabilities(cls, data: Any) -> Any:
        # data may be an ORM object or a plain dict
        if isinstance(data, dict):
            raw = data.get("capabilities")
            if isinstance(raw, str):
                data["capabilities"] = [c.strip() for c in raw.split(",") if c.strip()]
            elif raw is None:
                data["capabilities"] = []
        elif hasattr(data, "capabilities"):
            raw = data.capabilities
            if isinstance(raw, str):
                data.capabilities = [c.strip() for c in raw.split(",") if c.strip()]
            elif raw is None:
                data.capabilities = []
        return data
