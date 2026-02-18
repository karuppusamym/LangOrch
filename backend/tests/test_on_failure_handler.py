"""Tests for the global on_failure recovery handler in execution_service."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.execution_service import _run_on_failure_handler


def _make_ir(on_failure: str | None = None, node_ids: list[str] | None = None):
    """Create a minimal fake IR object for testing."""
    ir = MagicMock()
    ir.global_config = {"on_failure": on_failure} if on_failure else {}
    ir.procedure_id = "test_proc"
    ir.nodes = {nid: MagicMock() for nid in (node_ids or [])}
    return ir


class TestRunOnFailureHandler:

    @pytest.mark.asyncio
    async def test_returns_none_when_no_on_failure_configured(self):
        ir = _make_ir(on_failure=None)
        result = await _run_on_failure_handler(ir, {}, "run1", "some error", None, "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_on_failure_node_not_in_ir(self):
        # on_failure references a node that doesn't exist in the graph
        ir = _make_ir(on_failure="missing_node", node_ids=["node_a", "node_b"])
        result = await _run_on_failure_handler(ir, {}, "run1", "some error", None, "t1")
        assert result is None

    @pytest.mark.asyncio
    async def test_invokes_graph_when_node_exists(self):
        ir = _make_ir(on_failure="error_handler", node_ids=["error_handler", "node_a"])
        expected_state = {"vars": {"recovered": True}, "terminal_status": "success", "error": None}

        with patch("app.services.execution_service.build_graph") as mock_build, \
             patch("app.services.execution_service._invoke_graph_with_checkpointer", new_callable=AsyncMock) as mock_invoke:
            mock_build.return_value = MagicMock()
            mock_invoke.return_value = expected_state

            result = await _run_on_failure_handler(
                ir, {"vars": {}, "run_id": "run1"}, "run1", "step failed", None, "thread1"
            )

        assert result == expected_state
        mock_build.assert_called_once_with(ir, db_factory=None, entry_node_id="error_handler")
        # Thread ID should be namespaced with :on_failure
        call_args = mock_invoke.call_args
        assert call_args[0][2] == "thread1:on_failure"

    @pytest.mark.asyncio
    async def test_returns_none_when_handler_itself_raises(self):
        ir = _make_ir(on_failure="error_handler", node_ids=["error_handler"])

        with patch("app.services.execution_service.build_graph") as mock_build, \
             patch("app.services.execution_service._invoke_graph_with_checkpointer", new_callable=AsyncMock) as mock_invoke:
            mock_build.return_value = MagicMock()
            mock_invoke.side_effect = RuntimeError("handler crashed")

            result = await _run_on_failure_handler(
                ir, {}, "run1", "original error", None, "thread1"
            )

        # Should swallow the handler exception and return None gracefully
        assert result is None

    @pytest.mark.asyncio
    async def test_recovery_state_includes_error_info(self):
        """The recovery graph receives the error context in state."""
        ir = _make_ir(on_failure="cleanup_node", node_ids=["cleanup_node"])
        captured_state: dict = {}

        async def capture_invoke(graph, state, thread_id):
            captured_state.update(state)
            return {"vars": {}, "terminal_status": "success", "error": None}

        with patch("app.services.execution_service.build_graph") as mock_build, \
             patch("app.services.execution_service._invoke_graph_with_checkpointer", side_effect=capture_invoke):
            mock_build.return_value = MagicMock()
            await _run_on_failure_handler(
                ir,
                {"vars": {"x": 1}, "run_id": "r1"},
                "r1",
                "original error message",
                None,
                "t1",
            )

        # Recovery state should include the error message and correct entry node
        assert captured_state.get("current_node_id") == "cleanup_node"
        assert captured_state["error"]["message"] == "original error message"
        # Original vars preserved
        assert captured_state["vars"] == {"x": 1}
