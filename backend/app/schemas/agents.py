"""Pydantic models for agent instances."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, model_validator


class AgentCapability(BaseModel):
    name: str
    type: str = "tool"  # "tool" or "workflow"
    description: str | None = None
    estimated_duration_s: int | None = None
    is_batch: bool = False

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
    updated_at: datetime

    model_config = {"from_attributes": True}

    @model_validator(mode="before")
    @classmethod
    def _parse_capabilities(cls, data: Any) -> Any:
        import json

        def _parse_raw(raw: Any) -> list[dict[str, Any]]:
            if raw is None:
                return []
            if isinstance(raw, list):
                # Ensure elements are dictionaries (in case they're already AgentCapability objects or strings)
                parsed_list = []
                for item in raw:
                    if hasattr(item, "model_dump"):
                        parsed_list.append(item.model_dump())
                    elif isinstance(item, dict):
                        parsed_list.append(item)
                    elif isinstance(item, str):
                        parsed_list.append({"name": item, "type": "tool", "is_batch": False})
                return parsed_list
            if isinstance(raw, str):
                raw_str = raw.strip()
                if not raw_str:
                    return []
                # Check if it's JSON serialization of the new structured capability list
                if raw_str.startswith("[") and raw_str.endswith("]"):
                    try:
                        parsed_json = json.loads(raw_str)
                        if isinstance(parsed_json, list):
                            return _parse_raw(parsed_json)
                    except json.JSONDecodeError:
                        pass
                
                # Fallback to legacy comma-separated string format
                return [{"name": c.strip(), "type": "tool", "is_batch": False} for c in raw_str.split(",") if c.strip()]
            return []

        # data may be an ORM object or a plain dict
        if isinstance(data, dict):
            parsed = dict(data)
            parsed["capabilities"] = _parse_raw(parsed.get("capabilities"))
            return parsed

        if hasattr(data, "capabilities"):
            parsed_caps = _parse_raw(data.capabilities)

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
                "updated_at": data.updated_at,
            }

        return data
