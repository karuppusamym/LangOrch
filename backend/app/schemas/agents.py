"""Pydantic models for agent instances."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class AgentInstanceCreate(BaseModel):
    agent_id: str | None = None
    name: str
    channel: str
    base_url: str
    concurrency_limit: int = 1
    resource_key: str | None = None
    capabilities: list[str] | None = None


class AgentInstanceOut(BaseModel):
    agent_id: str
    name: str
    channel: str
    base_url: str
    status: str
    concurrency_limit: int
    resource_key: str
    capabilities: str | None = None
    updated_at: datetime

    model_config = {"from_attributes": True}
