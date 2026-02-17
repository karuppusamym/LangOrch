"""Catalog API — returns CKP action catalog and registry info."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter()

# Static action catalog from CKP syntax reference
ACTION_CATALOG: dict[str, list[str]] = {
    "generic": ["wait", "screenshot", "log", "set_checkpoint", "restore_checkpoint"],
    "desktop": [
        "launch_app", "activate_window", "wait_for_window", "wait_for_dialog",
        "click", "type", "press_key", "press_keys", "copy_to_clipboard",
        "paste_from_clipboard", "select_all_results", "click_cell",
        "read_excel_file", "close_window", "maximize_window", "minimize_window",
    ],
    "web": [
        "navigate", "wait_for_element", "click", "type", "clear",
        "extract_table_data", "wait_for_text", "scroll_to_element",
        "take_screenshot", "execute_javascript", "switch_frame",
        "switch_window", "upload_file", "download_file",
    ],
    "email": ["compose_email", "send_email", "read_email", "search_email", "download_attachment"],
    "api": ["http_request", "graphql_query", "soap_request", "websocket_connect"],
    "database": [
        "execute_query", "execute_procedure", "bulk_insert", "bulk_update",
        "transaction_begin", "transaction_commit", "transaction_rollback",
        "backup_data", "restore_data",
    ],
    "file": [
        "read_file", "write_file", "delete_file", "move_file", "copy_file",
        "list_directory", "create_directory", "zip_files", "unzip_files",
    ],
}


@router.get("/actions")
async def get_action_catalog():
    return ACTION_CATALOG
