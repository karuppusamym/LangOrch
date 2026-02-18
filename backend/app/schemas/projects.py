"""Pydantic models for projects."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel


class ProjectCreate(BaseModel):
    name: str
    description: str | None = None


class ProjectUpdate(BaseModel):
    name: str | None = None
    description: str | None = None


class ProjectOut(BaseModel):
    project_id: str
    name: str
    description: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
