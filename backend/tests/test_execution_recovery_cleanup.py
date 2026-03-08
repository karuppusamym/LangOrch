from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_execute_run_clears_affinity_after_on_failure_recovery():
    from app.runtime.executor_dispatch import _run_agent_affinity
    from app.services import execution_service, run_service

    run_id = "run-recover-affinity"
    affinity_key = f"{run_id}:web"
    _run_agent_affinity[affinity_key] = "agent-123"

    mock_run = MagicMock()
    mock_run.run_id = run_id
    mock_run.procedure_id = "proc-1"
    mock_run.procedure_version = "1.0.0"
    mock_run.last_node_id = None
    mock_run.input_vars_json = json.dumps({})
    mock_run.thread_id = run_id
    mock_run.output_vars_json = None

    mock_proc = MagicMock()
    mock_proc.status = "active"
    mock_proc.effective_date = None
    mock_proc.ckp_json = json.dumps(
        {
            "procedure_id": "proc-1",
            "version": "1.0.0",
            "global_config": {"on_failure": "recover_node"},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {"type": "sequence", "steps": []},
                    "recover_node": {"type": "sequence", "steps": []},
                },
            },
        }
    )

    fake_ir = MagicMock()
    fake_ir.global_config = {"on_failure": "recover_node"}
    fake_ir.variables_schema = {}
    fake_ir.nodes = {"start": MagicMock(), "recover_node": MagicMock()}
    fake_ir.start_node_id = "start"
    fake_ir.procedure_id = "proc-1"
    fake_ir.version = "1.0.0"

    mock_db = AsyncMock()
    mock_db.__aenter__ = AsyncMock(return_value=mock_db)
    mock_db.__aexit__ = AsyncMock(return_value=False)
    mock_db.commit = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=None)))

    with (
        patch.object(run_service, "get_run", new=AsyncMock(return_value=mock_run)),
        patch.object(run_service, "update_run_status", new=AsyncMock()) as mock_update_status,
        patch.object(run_service, "emit_event", new=AsyncMock()) as mock_emit_event,
        patch("app.services.procedure_service.get_procedure", new=AsyncMock(return_value=mock_proc)),
        patch("app.services.execution_service.parse_ckp", return_value=fake_ir),
        patch("app.services.execution_service.validate_ir", return_value=[]),
        patch("app.services.execution_service.bind_executors"),
        patch("app.services.execution_service.build_graph", return_value=MagicMock()),
        patch(
            "app.services.execution_service._invoke_graph_with_checkpointer",
            new=AsyncMock(return_value={"terminal_status": "success", "error": {"message": "boom"}, "vars": {}}),
        ),
        patch(
            "app.services.execution_service._run_on_failure_handler",
            new=AsyncMock(return_value={"terminal_status": "success", "error": None, "vars": {"recovered": True}}),
        ),
        patch("app.services.execution_service.record_run_started"),
        patch("app.services.execution_service.record_run_completed"),
    ):
        await execution_service.execute_run(run_id, lambda: mock_db)

    assert affinity_key not in _run_agent_affinity
    mock_update_status.assert_any_call(mock_db, run_id, "running")
    mock_update_status.assert_any_call(mock_db, run_id, "completed")
    recovered_events = [
        call.kwargs.get("payload", {})
        for call in mock_emit_event.await_args_list
        if len(call.args) >= 3 and call.args[2] == "run_completed"
    ]
    assert any(payload.get("recovered_via") == "recover_node" for payload in recovered_events)