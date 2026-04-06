"""Replay and simulation harness for agent capability contract testing."""

from __future__ import annotations

from typing import Any

from app.connectors.agent_client import AgentClient
from app.contracts.action_contracts import get_channel_for_action, normalize_action_name
from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest, parse_agent_capabilities
from app.contracts.swarm_contracts import verify_swarm_output
from app.db.models import AgentInstance
from app.schemas.agents import AgentContractResult, AgentContractTestOut


def _fixture_for_capability(capability: AgentCapability) -> dict[str, Any] | None:
    name = capability.name
    normalized = normalize_action_name(name)

    if name == "swarm.case_triage":
        return {
            "goal": "Classify the case and recommend a route",
            "context": {
                "ticket_text": "Urgent billing issue, invoice looks incorrect and customer is blocked today.",
                "channel": "email",
                "customer_tier": "enterprise",
            },
        }
    if name == "swarm.document_review":
        return {
            "goal": "Review document risk",
            "context": {
                "document_text": "This agreement includes indemnity, liability limits, and personal data transfer clauses.",
            },
        }
    if name == "swarm.failure_analysis":
        return {
            "goal": "Analyze the failed run and recommend the safest next step",
            "context": {
                "error_message": "HTTP 503 timeout from downstream dependency",
                "timeline": ["step_started", "step_failed"],
            },
        }

    if normalized in {"navigate", "new_tab"}:
        return {"url": "https://example.com"}
    if normalized in {"reload_page", "go_back", "go_forward", "get_current_url", "get_page_title", "get_tabs", "get_cookies", "clear_cookies", "get_local_storage", "get_dom", "get_accessibility_snapshot", "close", "close_tab"}:
        return {}
    if normalized in {"click", "double_click", "right_click", "hover", "focus", "blur", "scroll_into_view", "wait_for_element", "check", "uncheck", "extract_text", "extract_table_data", "select_all_text", "get_attribute", "query_dom"}:
        return {"target": "#demo"}
    if normalized == "type":
        return {"target": "#demo", "text": "contract test"}
    if normalized == "clear_field":
        return {"target": "#demo"}
    if normalized == "select_option":
        return {"target": "#demo-select", "value": "option-1"}
    if normalized == "upload_file":
        return {"target": "input[type=file]", "file_path": "C:/tmp/contract-test.txt"}
    if normalized == "download_file":
        return {"target": "a.download"}
    if normalized == "drag_and_drop":
        return {"source": "#source", "target": "#target"}
    if normalized == "press_key":
        return {"key": "Enter"}
    if normalized == "press_keys":
        return {"keys": ["Control", "A"]}
    if normalized == "scroll":
        return {"delta_y": 500}
    if normalized == "wait_for_navigation":
        return {"url_contains": "example.com"}
    if normalized == "wait_for_load_state":
        return {"state": "networkidle"}
    if normalized == "wait_for_network_idle":
        return {"idle_ms": 500}
    if normalized == "wait_for_url":
        return {"url_contains": "example.com"}
    if normalized == "wait_for_function":
        return {"expression": "() => true"}
    if normalized == "switch_tab":
        return {"index": 0}
    if normalized == "switch_frame":
        return {"name": "main"}
    if normalized == "switch_main_frame":
        return {}
    if normalized == "set_cookies":
        return {"cookies": [{"name": "session", "value": "demo", "domain": "example.com", "path": "/"}]}
    if normalized == "set_local_storage":
        return {"items": {"demo": "true"}}
    if normalized == "evaluate_js":
        return {"expression": "() => document.title"}
    if normalized == "cdp_send":
        return {"method": "Runtime.evaluate", "params": {"expression": "1 + 1"}}
    if normalized == "set_viewport":
        return {"width": 1280, "height": 720}
    if normalized == "set_geolocation":
        return {"latitude": 40.7128, "longitude": -74.0060}
    if normalized == "emulate_device":
        return {"device": "Desktop Chrome"}
    if normalized == "intercept_requests":
        return {"url_pattern": "**/*", "action": "continue"}
    if normalized == "set_extra_headers":
        return {"headers": {"X-Contract-Test": "1"}}
    if normalized == "launch_app":
        return {"application": "notepad"}
    if normalized in {"activate_window", "wait_for_window", "wait_for_dialog", "click_cell", "read_excel_file", "read_screen", "select_menu", "resize_window", "close_window", "maximize_window", "minimize_window"}:
        return {"target": "DemoWindow"}
    if normalized == "file_dialog":
        return {"file_path": "C:/tmp/contract-test.txt"}
    if normalized in {"compose_email", "send_email"}:
        return {"to": ["demo@example.com"], "subject": "Contract Test", "body": "Hello"}
    if normalized == "read_email":
        return {"message_id": "demo-message"}
    if normalized == "search_email":
        return {"query": "invoice"}
    if normalized == "download_attachment":
        return {"message_id": "demo-message", "attachment_id": "demo-attachment"}
    if normalized == "http_request":
        return {"method": "GET", "url": "https://example.com/api"}
    if normalized == "graphql_query":
        return {"url": "https://example.com/graphql", "query": "{ health }"}
    if normalized == "soap_request":
        return {"url": "https://example.com/soap", "body": "<Envelope />"}
    if normalized == "websocket_connect":
        return {"url": "wss://example.com/socket"}
    if normalized == "execute_query":
        return {"query": "SELECT 1"}
    if normalized == "execute_procedure":
        return {"name": "demo_proc", "params": {"id": 1}}
    if normalized in {"bulk_insert", "bulk_update", "export_data", "import_data", "create_connection", "close_connection", "transaction_begin", "transaction_commit", "transaction_rollback", "backup_data", "restore_data"}:
        return {}
    if normalized in {"read_file", "write_file", "delete_file", "move_file", "copy_file", "list_directory", "create_directory", "zip_files", "unzip_files"}:
        return {"path": "C:/tmp/contract-test.txt"}
    if normalized in {"generate_text", "summarize", "translate", "analyze_sentiment", "generate_code", "evaluate_response"}:
        return {"prompt": "Summarize this contract test in one line."}
    if normalized in {"classify_text", "extract_entities"}:
        return {"text": "OpenAI signed a contract in New York."}

    channel = get_channel_for_action(name)
    if channel:
        return {"input": f"contract-test:{channel}:{normalized}"}
    return None


def _validate_response(capability: AgentCapability, response: dict[str, Any]) -> dict[str, Any]:
    if capability.name.startswith("swarm."):
        return verify_swarm_output(capability.name, response)
    if not isinstance(response, dict):
        raise ValueError("Agent response result must be a JSON object")
    return response


def _filter_capabilities(
    capabilities: list[AgentCapability],
    selected: list[str] | None,
) -> list[AgentCapability]:
    if not selected:
        return capabilities
    selected_set = {item.strip().lower() for item in selected if item.strip()}
    return [cap for cap in capabilities if cap.name in selected_set]


async def run_agent_contract_tests(
    agent: AgentInstance,
    mode: str = "simulate",
    selected_capabilities: list[str] | None = None,
) -> AgentContractTestOut:
    """Run simulation or replay contract checks across an agent's capabilities."""
    capabilities = parse_agent_capabilities(agent.capabilities)
    if not capabilities:
        raise ValueError("Agent must declare explicit capabilities before contract testing")

    target_capabilities = _filter_capabilities(capabilities, selected_capabilities)
    results: list[AgentContractResult] = []
    client: AgentClient | None = None

    if mode == "replay":
        client = AgentClient(agent.base_url)

    try:
        for capability in target_capabilities:
            fixture = _fixture_for_capability(capability)
            if fixture is None:
                results.append(
                    AgentContractResult(
                        capability=capability.name,
                        capability_type=capability.type,
                        mode=mode,
                        status="failed",
                        error="No contract fixture available for capability",
                    )
                )
                continue

            request_payload = AgentExecuteRequest(
                action=capability.name,
                params=fixture,
                run_id=f"contract-{mode}-run",
                node_id="contract_node",
                step_id=f"contract_{capability.name.replace('.', '_')}",
            ).model_dump()

            if mode == "simulate":
                results.append(
                    AgentContractResult(
                        capability=capability.name,
                        capability_type=capability.type,
                        mode=mode,
                        status="passed",
                        request=request_payload,
                    )
                )
                continue

            try:
                assert client is not None
                response = await client.execute_action(
                    action=capability.name,
                    params=fixture,
                    run_id=request_payload["run_id"],
                    node_id=request_payload["node_id"],
                    step_id=request_payload["step_id"],
                )
                validated = _validate_response(capability, response)
                results.append(
                    AgentContractResult(
                        capability=capability.name,
                        capability_type=capability.type,
                        mode=mode,
                        status="passed",
                        request=request_payload,
                        response=validated,
                    )
                )
            except Exception as exc:
                results.append(
                    AgentContractResult(
                        capability=capability.name,
                        capability_type=capability.type,
                        mode=mode,
                        status="failed",
                        request=request_payload,
                        error=str(exc),
                    )
                )
    finally:
        if client is not None:
            await client.close()

    passed = sum(1 for result in results if result.status == "passed")
    failed = sum(1 for result in results if result.status == "failed")
    skipped = sum(1 for result in results if result.status == "skipped")
    return AgentContractTestOut(
        agent_id=agent.agent_id,
        mode=mode,
        total=len(results),
        passed=passed,
        failed=failed,
        skipped=skipped,
        results=results,
    )
