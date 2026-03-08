from __future__ import annotations

import json
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _make_state() -> dict:
    return {
        "vars": {"parent_value": "x"},
        "secrets": {},
        "run_id": "run-subflow-test",
        "procedure_id": "parent-proc",
        "procedure_version": "1.0.0",
        "current_node_id": "sub",
        "next_node_id": None,
        "error": None,
        "terminal_status": None,
    }


def _make_node(on_failure: str = "continue"):
    node = MagicMock()
    node.node_id = "sub"
    payload = MagicMock()
    payload.procedure_id = "child-proc"
    payload.version = "1.0.0"
    payload.inherit_context = False
    payload.input_mapping = {}
    payload.output_mapping = {}
    payload.next_node_id = "after_subflow"
    payload.on_failure = on_failure
    node.payload = payload
    return node


def _make_db_factory(captured_events: list[dict]):
    mock_db = AsyncMock()

    async def fake_emit_event(db, run_id, event_type, node_id=None, payload=None, **kwargs):
        captured_events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "node_id": node_id,
                "payload": payload,
            }
        )

    @asynccontextmanager
    async def db_factory():
        yield mock_db

    return db_factory, mock_db, fake_emit_event


class TestSubflowFailureEvents:
    @pytest.mark.asyncio
    async def test_subflow_continue_emits_subflow_failed_event(self):
        from app.runtime.node_executors import execute_subflow

        captured: list[dict] = []
        db_factory, _mock_db, fake_emit = _make_db_factory(captured)
        node = _make_node(on_failure="continue")
        state = _make_state()

        child_proc = MagicMock()
        child_proc.procedure_id = "child-proc"
        child_proc.version = "1.0.0"
        child_proc.ckp_json = json.dumps(
            {
                "procedure_id": "child-proc",
                "version": "1.0.0",
                "workflow_graph": {"start_node": "start", "nodes": {"start": {"type": "sequence", "steps": []}}},
            }
        )

        child_ir = MagicMock()
        child_ir.procedure_id = "child-proc"
        child_ir.version = "1.0.0"
        child_ir.start_node_id = "start"

        with (
            patch("app.services.procedure_service.get_procedure", new=AsyncMock(return_value=child_proc)),
            patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=fake_emit)),
            patch("app.compiler.parser.parse_ckp", return_value=child_ir),
            patch("app.compiler.validator.validate_ir", return_value=[]),
            patch("app.compiler.binder.bind_executors"),
            patch("app.runtime.graph_builder.build_graph", return_value=MagicMock()),
            patch(
                "app.runtime.node_executors._invoke_with_optional_checkpointer",
                new=AsyncMock(return_value={"error": {"message": "child boom"}, "terminal_status": "failed"}),
            ),
        ):
            result = await execute_subflow(node, state, db_factory=db_factory)

        assert result["current_node_id"] == "sub"
        assert result["next_node_id"] == "after_subflow"
        event_types = [event["event_type"] for event in captured]
        assert event_types == ["subflow_started", "subflow_failed"]
        failed_event = captured[1]
        assert failed_event["payload"]["on_failure"] == "continue"
        assert failed_event["payload"]["error"]["message"] == "child boom"

    @pytest.mark.asyncio
    async def test_subflow_fail_parent_emits_subflow_failed_event(self):
        from app.runtime.node_executors import execute_subflow

        captured: list[dict] = []
        db_factory, _mock_db, fake_emit = _make_db_factory(captured)
        node = _make_node(on_failure="fail_parent")
        state = _make_state()

        child_proc = MagicMock()
        child_proc.procedure_id = "child-proc"
        child_proc.version = "1.0.0"
        child_proc.ckp_json = json.dumps(
            {
                "procedure_id": "child-proc",
                "version": "1.0.0",
                "workflow_graph": {"start_node": "start", "nodes": {"start": {"type": "sequence", "steps": []}}},
            }
        )

        child_ir = MagicMock()
        child_ir.procedure_id = "child-proc"
        child_ir.version = "1.0.0"
        child_ir.start_node_id = "start"

        with (
            patch("app.services.procedure_service.get_procedure", new=AsyncMock(return_value=child_proc)),
            patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=fake_emit)),
            patch("app.compiler.parser.parse_ckp", return_value=child_ir),
            patch("app.compiler.validator.validate_ir", return_value=[]),
            patch("app.compiler.binder.bind_executors"),
            patch("app.runtime.graph_builder.build_graph", return_value=MagicMock()),
            patch(
                "app.runtime.node_executors._invoke_with_optional_checkpointer",
                new=AsyncMock(return_value={"error": {"message": "child boom"}, "terminal_status": "failed"}),
            ),
        ):
            result = await execute_subflow(node, state, db_factory=db_factory)

        assert result["terminal_status"] == "failed"
        assert result["error"]["message"] == "Subflow execution failed"
        event_types = [event["event_type"] for event in captured]
        assert event_types == ["subflow_started", "subflow_failed"]