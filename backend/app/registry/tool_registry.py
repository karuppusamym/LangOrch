"""Tool registry — maps CKP actions to executors (agent, MCP, or internal)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("langorch.registry.tool")

# Static action catalog — mirrors CKP spec action_catalog
ACTION_CATALOG: dict[str, list[str]] = {
    "web": [
        "navigate_to", "click_element", "type_text", "select_option",
        "extract_data", "wait_for_element", "scroll_page", "take_screenshot",
        "switch_tab", "close_tab", "refresh_page", "submit_form",
        "hover_element", "drag_and_drop", "handle_alert", "execute_javascript",
    ],
    "desktop": [
        "open_application", "click_element", "type_text", "keyboard_shortcut",
        "select_menu", "read_screen", "wait_for_window", "close_application",
        "right_click", "double_click", "drag_and_drop", "take_screenshot",
        "file_dialog", "resize_window", "minimize_window", "maximize_window",
    ],
    "email": [
        "read_emails", "send_email", "forward_email", "reply_email",
        "search_emails", "download_attachment", "create_draft", "move_email",
        "delete_email", "mark_read", "get_email_count", "extract_email_data",
    ],
    "api": [
        "http_request", "graphql_query", "soap_call", "webhook_send",
        "parse_response", "authenticate", "set_headers", "upload_file",
    ],
    "database": [
        "execute_query", "execute_stored_procedure", "bulk_insert",
        "export_data", "import_data", "create_connection", "close_connection",
        "begin_transaction", "commit_transaction", "rollback_transaction",
    ],
    "llm": [
        "generate_text", "classify_text", "extract_entities",
        "summarize", "translate", "analyze_sentiment", "generate_code",
        "evaluate_response",
    ],
    "generic": [
        "log", "wait", "set_variable", "calculate", "format_data",
        "parse_json", "parse_csv", "generate_id", "get_timestamp",
        "send_notification",
    ],
}


def get_channel_for_action(action: str) -> str | None:
    """Return the channel that owns a given action name."""
    for channel, actions in ACTION_CATALOG.items():
        if action in actions:
            return channel
    return None


def get_actions_for_channel(channel: str) -> list[str]:
    """Return all actions for a given channel."""
    return ACTION_CATALOG.get(channel, [])


def is_internal_action(action: str) -> bool:
    """Check if action can be handled internally (no agent/MCP needed)."""
    return action in ACTION_CATALOG.get("generic", [])
