"""Runtime tests for workflow_dispatch_mode behavior in execute_sequence."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


from app.runtime.node_executors import execute_sequence


def _make_step(*, mode: str | None = None):
    step = MagicMock()
    step.step_id = "wf_step"
    step.action = "run_long_workflow"
    step.params = {"input": "x"}
    step.output_variable = "wf_result"
    step.idempotency_key = None
    step.retry_on_failure = False
    step.max_retries = 0
    step.delay_ms = 0
    step.wait_ms = None
    step.wait_after_ms = None
    step.timeout_ms = None
    step.error_handlers = []
    step.executor_binding = None
    step.retry_config = None
    step.workflow_dispatch_mode = mode
    return step


def _make_node(step):
    node = MagicMock()
    node.node_id = "n_wf"
    node.payload = MagicMock()
    node.payload.steps = [step]
    node.payload.error_handlers = []
    node.sla = None
    return node


def _base_state(*, global_mode: str | None = None):
    global_config = {}
    if global_mode is not None:
        global_config["workflow_dispatch_mode"] = global_mode
    return {
        "vars": {},
        "secrets": {},
        "run_id": "run-wf-mode",
        "current_node_id": "n_wf",
        "next_node_id": None,
        "error": None,
        "execution_mode": "production",
        "global_config": global_config,
    }


def _make_db_factory(mock_db):
    @asynccontextmanager
    async def db_factory():
        yield mock_db

    return db_factory


async def test_workflow_dispatch_mode_sync_runs_inline_without_pause():
    step = _make_step(mode="sync")
    node = _make_node(step)
    state = _base_state()

    binding = MagicMock()
    binding.kind = "agent_http"
    binding.ref = "http://agent:9000"

    emitted_events: list[str] = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    db_factory = _make_db_factory(mock_db)

    with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=(binding, "workflow"))), \
         patch("app.runtime.executor_dispatch.dispatch_to_agent", new=AsyncMock(return_value={"ok": True, "mode": "sync"})) as mock_dispatch, \
         patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_events.append(event_type))), \
         patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
         patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
         patch("app.runtime.node_executors._acquire_agent_lease", new=AsyncMock(return_value=None)), \
         patch("app.runtime.node_executors._release_lease", new=AsyncMock()):
        result = await execute_sequence(node, state, db_factory=db_factory)

    assert mock_dispatch.await_count == 1
    assert result.get("_workflow_pending") is not True
    assert "workflow_delegated" not in emitted_events
    assert result["vars"]["wf_result"] == {"ok": True, "mode": "sync"}


async def test_workflow_dispatch_mode_async_pauses_and_emits_delegation():
    step = _make_step(mode="async")
    node = _make_node(step)
    state = _base_state()

    binding = MagicMock()
    binding.kind = "agent_http"
    binding.ref = "http://agent:9000"

    emitted_calls: list[tuple[str, dict]] = []

    mock_db = AsyncMock()
    mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=lambda: None))
    db_factory = _make_db_factory(mock_db)

    async def _capture_emit(db, run_id, event_type, **kw):
        emitted_calls.append((event_type, kw))

    def _consume_task(coro):
        coro.close()
        return MagicMock()

    with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=(binding, "workflow"))), \
         patch("app.runtime.executor_dispatch.dispatch_to_agent", new=AsyncMock()) as mock_dispatch, \
            patch("app.runtime.node_executors.asyncio.create_task", side_effect=_consume_task) as mock_create_task, \
         patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=_capture_emit)), \
         patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
         patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()):
        result = await execute_sequence(node, state, db_factory=db_factory)

    assert mock_dispatch.await_count == 0
    assert mock_create_task.call_count == 1
    assert result.get("_workflow_pending") is True
    assert result.get("_workflow_resume_node") == "n_wf"
    assert result.get("_workflow_resume_step") == "wf_step"

    delegated = [payload for (event_type, payload) in emitted_calls if event_type == "workflow_delegated"]
    assert delegated, "workflow_delegated event should be emitted for async mode"
    assert delegated[0]["payload"]["dispatch_mode"] == "async"
