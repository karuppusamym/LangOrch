"""Tool registry â€” maps CKP actions to executors (agent, MCP, or internal)."""

from __future__ import annotations

import logging

from app.contracts.action_contracts import (
    get_action_catalog,
    get_actions_for_channel as _get_actions_for_channel,
    get_channel_for_action as _get_channel_for_action,
    is_internal_action as _is_internal_action,
)

logger = logging.getLogger("langorch.registry.tool")

ACTION_CATALOG = get_action_catalog()


def get_channel_for_action(action: str) -> str | None:
    """Return the channel that owns a given action name."""
    return _get_channel_for_action(action)


def get_actions_for_channel(channel: str) -> list[str]:
    """Return all actions for a given channel."""
    return _get_actions_for_channel(channel)


def is_internal_action(action: str) -> bool:
    """Check if action can be handled internally (no agent/MCP needed)."""
    return _is_internal_action(action)
