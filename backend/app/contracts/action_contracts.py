"""Canonical action catalog and normalization helpers."""

from __future__ import annotations

from collections import OrderedDict


_BASE_ACTION_CATALOG: dict[str, list[str]] = {
    "generic": [
        "wait",
        "screenshot",
        "log",
        "set_checkpoint",
        "restore_checkpoint",
        "set_variable",
        "calculate",
        "format_data",
        "parse_json",
        "parse_csv",
        "generate_id",
        "get_timestamp",
        "send_notification",
    ],
    "desktop": [
        "launch_app",
        "open_application",
        "attach_window",
        "activate_window",
        "wait_for_window",
        "wait_for_dialog",
        "wait_for_screen",
        "click",
        "click_element",
        "type",
        "type_text",
        "press_key",
        "press_keys",
        "keyboard_shortcut",
        "find_element",
        "find_text",
        "locate_by_text",
        "locate_by_image",
        "ocr_screen",
        "send_pf_key",
        "copy_to_clipboard",
        "paste_from_clipboard",
        "select_all_results",
        "click_cell",
        "read_excel_file",
        "read_screen",
        "select_menu",
        "right_click",
        "double_click",
        "drag_and_drop",
        "file_dialog",
        "resize_window",
        "close_window",
        "close_application",
        "maximize_window",
        "minimize_window",
        "screenshot",
        "take_screenshot",
    ],
    "web": [
        "navigate",
        "navigate_to",
        "reload_page",
        "refresh_page",
        "go_back",
        "go_forward",
        "get_current_url",
        "get_page_title",
        "wait_for_element",
        "wait_for_navigation",
        "wait_for_load_state",
        "wait_for_network_idle",
        "wait_for_url",
        "wait_for_function",
        "wait_for_text",
        "click",
        "click_element",
        "double_click",
        "right_click",
        "hover",
        "type",
        "type_text",
        "clear",
        "clear_field",
        "select_option",
        "check",
        "uncheck",
        "upload_file",
        "download_file",
        "drag_and_drop",
        "press_key",
        "focus",
        "blur",
        "scroll",
        "scroll_page",
        "scroll_to_element",
        "scroll_into_view",
        "get_attribute",
        "extract_text",
        "extract_data",
        "extract_table_data",
        "select_all_text",
        "take_screenshot",
        "screenshot",
        "execute_javascript",
        "evaluate_js",
        "handle_alert",
        "switch_frame",
        "switch_main_frame",
        "switch_window",
        "switch_tab",
        "new_tab",
        "close_tab",
        "get_tabs",
        "get_cookies",
        "set_cookies",
        "clear_cookies",
        "get_local_storage",
        "set_local_storage",
        "cdp_send",
        "set_viewport",
        "set_geolocation",
        "emulate_device",
        "intercept_requests",
        "set_extra_headers",
        "get_dom",
        "query_dom",
        "get_accessibility_snapshot",
        "ai_locate",
        "close",
    ],
    "email": [
        "compose_email",
        "create_draft",
        "send_email",
        "read_email",
        "read_emails",
        "search_email",
        "search_emails",
        "download_attachment",
        "forward_email",
        "reply_email",
        "move_email",
        "delete_email",
        "mark_read",
        "get_email_count",
        "extract_email_data",
    ],
    "api": [
        "http_request",
        "graphql_query",
        "soap_request",
        "soap_call",
        "webhook_send",
        "websocket_connect",
        "parse_response",
        "authenticate",
        "set_headers",
        "upload_file",
    ],
    "database": [
        "execute_query",
        "execute_procedure",
        "execute_stored_procedure",
        "bulk_insert",
        "bulk_update",
        "export_data",
        "import_data",
        "create_connection",
        "close_connection",
        "transaction_begin",
        "transaction_commit",
        "transaction_rollback",
        "begin_transaction",
        "commit_transaction",
        "rollback_transaction",
        "backup_data",
        "restore_data",
    ],
    "file": [
        "read_file",
        "write_file",
        "delete_file",
        "move_file",
        "copy_file",
        "list_directory",
        "create_directory",
        "zip_files",
        "unzip_files",
    ],
    "terminal": [
        "connect_session",
        "disconnect_session",
        "send_keys",
        "send_pf_key",
        "read_screen",
        "wait_for_screen",
        "set_cursor",
        "extract_field",
        "submit_screen",
    ],
    "llm": [
        "generate_text",
        "classify_text",
        "extract_entities",
        "summarize",
        "translate",
        "analyze_sentiment",
        "generate_code",
        "evaluate_response",
    ],
    "swarm": [
        "swarm.case_triage",
        "swarm.document_review",
        "swarm.failure_analysis",
    ],
}

ACTION_ALIASES: dict[str, str] = {
    "navigate_to": "navigate",
    "click_element": "click",
    "type_text": "type",
    "take_screenshot": "screenshot",
    "refresh_page": "reload_page",
    "execute_javascript": "evaluate_js",
    "extract_data": "extract_text",
    "scroll_page": "scroll",
    "scroll_to_element": "scroll_into_view",
    "clear": "clear_field",
    "switch_window": "switch_tab",
    "open_application": "launch_app",
    "keyboard_shortcut": "press_keys",
    "close_application": "close_window",
    "read_emails": "read_email",
    "search_emails": "search_email",
    "soap_call": "soap_request",
    "execute_stored_procedure": "execute_procedure",
    "begin_transaction": "transaction_begin",
    "commit_transaction": "transaction_commit",
    "rollback_transaction": "transaction_rollback",
}

CHANNEL_PREFIX_ALIASES: dict[str, str] = {
    "browser": "web",
    "web": "web",
    "desktop": "desktop",
    "email": "email",
    "mail": "email",
    "api": "api",
    "db": "database",
    "database": "database",
    "file": "file",
    "llm": "llm",
    "swarm": "swarm",
}

INTERNAL_ACTIONS: set[str] = {
    "log",
    "wait",
    "set_variable",
    "calculate",
    "format_data",
    "parse_json",
    "parse_csv",
    "generate_id",
    "get_timestamp",
    "set_checkpoint",
    "restore_checkpoint",
    "api.get",
    "api.post",
    "api.put",
    "api.patch",
    "api.delete",
}


def normalize_action_name(action: str | None) -> str:
    """Return a canonical action name for comparisons and routing."""
    if not action:
        return ""

    normalized = action.strip().lower()
    if not normalized:
        return ""

    alias = ACTION_ALIASES.get(normalized)
    if alias:
        return alias

    if "." in normalized:
        prefix, candidate = normalized.split(".", 1)
        channel = CHANNEL_PREFIX_ALIASES.get(prefix)
        if channel:
            candidate = ACTION_ALIASES.get(candidate, candidate)
            if candidate in _BASE_ACTION_CATALOG.get(channel, []):
                return candidate

    return normalized


def get_action_catalog(include_aliases: bool = True) -> dict[str, list[str]]:
    """Return the public action catalog, optionally expanded with aliases."""
    if not include_aliases:
        return {channel: list(actions) for channel, actions in _BASE_ACTION_CATALOG.items()}

    expanded: dict[str, list[str]] = {}
    for channel, actions in _BASE_ACTION_CATALOG.items():
        ordered = OrderedDict((action, None) for action in actions)
        for alias, canonical in ACTION_ALIASES.items():
            if canonical in actions:
                ordered.setdefault(alias, None)
        for prefix, mapped_channel in CHANNEL_PREFIX_ALIASES.items():
            if mapped_channel != channel or prefix == channel:
                continue
            for action in actions:
                if "." not in action:
                    ordered.setdefault(f"{prefix}.{action}", None)
        expanded[channel] = list(ordered.keys())
    return expanded


def get_channel_for_action(action: str) -> str | None:
    """Return the channel that owns a given action name."""
    normalized = normalize_action_name(action)
    for channel, actions in _BASE_ACTION_CATALOG.items():
        if normalized in actions:
            return channel
    return None


def get_actions_for_channel(channel: str, include_aliases: bool = True) -> list[str]:
    """Return all known actions for a given channel."""
    return get_action_catalog(include_aliases=include_aliases).get(channel, [])


def is_internal_action(action: str) -> bool:
    """Check if an action is executed inside the orchestrator process."""
    normalized = normalize_action_name(action)
    return normalized in INTERNAL_ACTIONS or action in INTERNAL_ACTIONS
