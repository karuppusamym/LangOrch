"""Catalog API â€” returns the shared action catalog."""

from __future__ import annotations

from fastapi import APIRouter

from app.contracts.action_contracts import get_action_catalog

router = APIRouter()


@router.get("/actions")
async def get_actions():
    return get_action_catalog()
