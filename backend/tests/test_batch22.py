"""
Tests for Batch 22 features:
  1. Dynamic internal step timeout — dynamically-resolved internal binding now applies timeout
  2. screenshot_on_fail — screenshot_requested event emitted on step failure when flag set
  3. mock_external_calls — returns stub result instead of calling real agent/MCP
  4. test_data_overrides — per-step result override applied before dispatch
  5. Procedures search param — keyword search across procedure_id, name, description, metadata
  6. CHECKPOINT_RETENTION_DAYS setting — present in config with correct default
  7. procedure_service.list_procedures search — correct filtering logic
  8. _checkpoint_retention_loop — callable, runs without error on empty DB
  9. _file_watch_trigger_loop — callable, skips registration with no event_source
 10. GitHub Actions CI file — exists and contains required jobs
"""

from __future__ import annotations

import asyncio
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_db_factory(captured_events=None):
    """Return a db_factory whose db mock captures emit_event calls."""
    captured_events = captured_events if captured_events is not None else []
    mock_db = AsyncMock()

    @asynccontextmanager
    async def db_factory():
        yield mock_db

    return db_factory, captured_events


def _make_step(
    *,
    action="do_thing",
    step_id="s1",
    timeout_ms=None,
    retry_on_failure=False,
    binding_kind=None,  # None → dynamic resolve path
):
    step = MagicMock()
    step.step_id = step_id
    step.action = action
    step.params = {}
    step.output_variable = None
    step.idempotency_key = None
    step.retry_on_failure = retry_on_failure
    step.max_retries = 0
    step.delay_ms = 0
    step.wait_ms = None
    step.wait_after_ms = None
    step.timeout_ms = timeout_ms
    step.error_handlers = []
    if binding_kind:
        step.executor_binding = MagicMock()
        step.executor_binding.kind = binding_kind
    else:
        step.executor_binding = None  # force dynamic resolve path
    return step


def _make_node(steps, *, node_id="n1"):
    node = MagicMock()
    node.node_id = node_id
    node.payload = MagicMock()
    node.payload.steps = steps
    node.payload.error_handlers = []
    node.sla = None
    return node


def _base_state(*, run_id="run-22", global_config=None):
    return {
        "vars": {},
        "secrets": {},
        "run_id": run_id,
        "current_node_id": "n1",
        "next_node_id": None,
        "error": None,
        "execution_mode": "production",
        "global_config": global_config or {},
    }


@asynccontextmanager
async def _null_db():
    db = AsyncMock()
    db.commit = AsyncMock()
    yield db


def _db_factory():
    return _null_db()


# ---------------------------------------------------------------------------
# 1. Dynamic internal step timeout
# ---------------------------------------------------------------------------


class TestDynamicInternalTimeout:
    """Dynamic-resolution internal binding respects step.timeout_ms."""

    async def test_dynamic_internal_no_timeout_succeeds(self):
        """Without timeout, internal binding runs normally."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="log", timeout_ms=None)
        node = _make_node([step])
        state = _base_state()

        binding = MagicMock()
        binding.kind = "internal"

        db_factory, _ = _make_db_factory()

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.node_executors._execute_step_action", new=AsyncMock(return_value={"ok": True})), \
             patch("app.services.run_service.emit_event", new=AsyncMock()), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
             patch("app.runtime.node_executors._mark_step_failed", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None

    async def test_dynamic_internal_timeout_fires(self):
        """Dynamic internal binding raises TimeoutError when step.timeout_ms exceeded."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="log", timeout_ms=50)
        node = _make_node([step])
        state = _base_state()

        binding = MagicMock()
        binding.kind = "internal"

        db_factory, _ = _make_db_factory()

        async def _slow_action(*_a, **_kw):
            await asyncio.sleep(10)
            return {}

        emitted_types = []

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.node_executors._execute_step_action", new=_slow_action), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
             patch("app.runtime.node_executors._mark_step_failed", new=AsyncMock()), \
             patch("app.runtime.node_executors.record_step_timeout") as mock_rpt:
            with pytest.raises((TimeoutError, asyncio.TimeoutError)):
                await execute_sequence(node, state, db_factory=db_factory)

        assert "step_timeout" in emitted_types
        mock_rpt.assert_called_once_with("n1", "s1", 50)


# ---------------------------------------------------------------------------
# 2. screenshot_on_fail
# ---------------------------------------------------------------------------


class TestScreenshotOnFail:
    """screenshot_on_fail global_config flag triggers screenshot_requested event."""

    async def test_screenshot_event_emitted_on_step_failure(self):
        """When screenshot_on_fail=True and step fails, screenshot_requested is emitted."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="fail_action", timeout_ms=None)
        node = _make_node([step])
        state = _base_state(global_config={"screenshot_on_fail": True})

        binding = MagicMock()
        binding.kind = "internal"

        db_factory, _ = _make_db_factory()

        emitted_types = []

        async def _fail_action(*_a, **_kw):
            raise RuntimeError("deliberate failure")

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.node_executors._execute_step_action", new=_fail_action), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
             patch("app.runtime.node_executors._mark_step_failed", new=AsyncMock()):
            with pytest.raises(RuntimeError):
                await execute_sequence(node, state, db_factory=db_factory)

        assert "screenshot_requested" in emitted_types

    async def test_screenshot_event_not_emitted_when_flag_false(self):
        """When screenshot_on_fail=False (default), screenshot_requested is NOT emitted."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="fail_action", timeout_ms=None)
        node = _make_node([step])
        state = _base_state(global_config={"screenshot_on_fail": False})

        binding = MagicMock()
        binding.kind = "internal"

        db_factory, _ = _make_db_factory()

        emitted_types = []

        async def _fail_action(*_a, **_kw):
            raise RuntimeError("deliberate failure")

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.node_executors._execute_step_action", new=_fail_action), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
             patch("app.runtime.node_executors._mark_step_failed", new=AsyncMock()):
            with pytest.raises(RuntimeError):
                await execute_sequence(node, state, db_factory=db_factory)

        assert "screenshot_requested" not in emitted_types


# ---------------------------------------------------------------------------
# 3. mock_external_calls
# ---------------------------------------------------------------------------


class TestMockExternalCalls:
    """mock_external_calls global_config skips real agent/MCP dispatch."""

    async def test_mock_external_agent_http(self):
        """agent_http binding returns stub when mock_external_calls=True."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="click_button", timeout_ms=None)
        node = _make_node([step])
        state = _base_state(global_config={"mock_external_calls": True})

        binding = MagicMock()
        binding.kind = "agent_http"
        binding.ref = "http://agent:9000"

        db_factory, _ = _make_db_factory()
        emitted_types = []

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None
        assert "step_mock_applied" in emitted_types

    async def test_mock_external_mcp_tool(self):
        """mcp_tool binding returns stub when mock_external_calls=True."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="run_tool", timeout_ms=None)
        node = _make_node([step])
        state = _base_state(global_config={"mock_external_calls": True})

        binding = MagicMock()
        binding.kind = "mcp_tool"
        binding.ref = "http://mcp:8001"

        db_factory, _ = _make_db_factory()
        emitted_types = []

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None
        assert "step_mock_applied" in emitted_types

    async def test_mock_external_false_still_dispatches(self):
        """When mock_external_calls=False, normal dispatch is called."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="click_button", timeout_ms=None)
        node = _make_node([step])
        state = _base_state(global_config={"mock_external_calls": False})

        binding = MagicMock()
        binding.kind = "agent_http"
        binding.ref = "http://agent:9000"

        db_factory, _ = _make_db_factory()

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.executor_dispatch.dispatch_to_agent", new=AsyncMock(return_value={"ok": True})), \
             patch("app.services.run_service.emit_event", new=AsyncMock()), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()), \
             patch("app.runtime.node_executors._acquire_agent_lease", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._release_lease", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None


# ---------------------------------------------------------------------------
# 4. test_data_overrides
# ---------------------------------------------------------------------------


class TestTestDataOverrides:
    """test_data_overrides returns configured result for specific step_id."""

    async def test_override_returned_for_matching_step(self):
        """Step matching test_data_overrides key gets override result, not dispatched."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="api_call", step_id="api_step", timeout_ms=None)
        step.output_variable = "api_result"
        node = _make_node([step])
        state = _base_state(global_config={
            "test_data_overrides": {"api_step": {"status": "ok", "items": [1, 2, 3]}}
        })

        binding = MagicMock()
        binding.kind = "agent_http"
        binding.ref = "http://agent:9000"

        db_factory, _ = _make_db_factory()
        emitted_types = []

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.services.run_service.emit_event",
                   new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: emitted_types.append(event_type))), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None
        assert "step_test_override_applied" in emitted_types
        # Output variable should be set from override
        assert result["vars"].get("api_result") == {"status": "ok", "items": [1, 2, 3]}

    async def test_override_not_applied_for_non_matching_step(self):
        """Steps not in test_data_overrides are dispatched normally."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(action="log", step_id="other_step", timeout_ms=None)
        node = _make_node([step])
        # Override for a different step
        state = _base_state(global_config={
            "test_data_overrides": {"different_step": {"result": "x"}}
        })

        binding = MagicMock()
        binding.kind = "internal"

        db_factory, _ = _make_db_factory()

        with patch("app.runtime.executor_dispatch.resolve_executor", new=AsyncMock(return_value=binding)), \
             patch("app.runtime.node_executors._execute_step_action", new=AsyncMock(return_value={})), \
             patch("app.services.run_service.emit_event", new=AsyncMock()), \
             patch("app.runtime.node_executors._get_completed_step_result", new=AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", new=AsyncMock()):
            result = await execute_sequence(node, state, db_factory=db_factory)

        assert result.get("error") is None


# ---------------------------------------------------------------------------
# 5. Procedures search — API endpoint
# ---------------------------------------------------------------------------


class TestProceduresSearchAPI:
    """GET /api/procedures?search= filters by keyword."""

    def test_list_procedures_has_search_param(self):
        """The list_procedures endpoint accepts a search query parameter."""
        import inspect
        from app.api.procedures import list_procedures

        sig = inspect.signature(list_procedures)
        assert "search" in sig.parameters

    def test_list_procedures_service_has_search_param(self):
        """procedure_service.list_procedures accepts a search parameter."""
        import inspect
        from app.services.procedure_service import list_procedures as svc_lp

        sig = inspect.signature(svc_lp)
        assert "search" in sig.parameters


# ---------------------------------------------------------------------------
# 6. procedure_service.list_procedures — search logic
# ---------------------------------------------------------------------------


class TestProcedureServiceSearch:
    """list_procedures search filters correctly."""

    async def test_search_by_procedure_id(self):
        """Search matches procedure_id substring."""
        from app.services.procedure_service import list_procedures

        db = AsyncMock()
        proc = MagicMock()
        proc.procedure_id = "my_invoice_workflow"
        proc.name = "Invoice Workflow"
        proc.description = None
        proc.retrieval_metadata_json = None
        proc.project_id = None
        proc.status = "active"
        proc.created_at = None

        # Simulate db.execute returning our mock proc
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [proc]
        db.execute = AsyncMock(return_value=result_mock)

        found = await list_procedures(db, search="invoice")
        assert proc in found

    async def test_search_no_match(self):
        """Search returns empty list when no procedures match."""
        from app.services.procedure_service import list_procedures

        db = AsyncMock()
        proc = MagicMock()
        proc.procedure_id = "payment_processing"
        proc.name = "Payment Processing"
        proc.description = "Handles payments"
        proc.retrieval_metadata_json = None
        proc.project_id = None
        proc.status = "active"
        proc.created_at = None

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [proc]
        db.execute = AsyncMock(return_value=result_mock)

        found = await list_procedures(db, search="invoice")
        assert found == []

    async def test_search_by_retrieval_metadata_keyword(self):
        """Search matches retrieval_metadata keywords field."""
        import json
        from app.services.procedure_service import list_procedures

        db = AsyncMock()
        proc = MagicMock()
        proc.procedure_id = "data_pipeline"
        proc.name = "Data Pipeline"
        proc.description = None
        proc.retrieval_metadata_json = json.dumps({
            "domain": "finance",
            "keywords": ["ledger", "reconciliation", "audit"],
            "intents": [],
            "tags": [],
        })
        proc.project_id = None
        proc.status = "active"
        proc.created_at = None

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [proc]
        db.execute = AsyncMock(return_value=result_mock)

        found = await list_procedures(db, search="reconciliation")
        assert proc in found

    async def test_search_none_returns_all(self):
        """search=None returns all procedures unfiltered."""
        from app.services.procedure_service import list_procedures

        db = AsyncMock()
        procs = [MagicMock() for _ in range(3)]
        for p in procs:
            p.procedure_id = f"proc_{id(p)}"
            p.name = "Proc"
            p.description = None
            p.retrieval_metadata_json = None
            p.project_id = None
            p.status = "active"
            p.created_at = None

        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = procs
        db.execute = AsyncMock(return_value=result_mock)

        found = await list_procedures(db, search=None)
        assert len(found) == 3


# ---------------------------------------------------------------------------
# 7. Config: CHECKPOINT_RETENTION_DAYS
# ---------------------------------------------------------------------------


class TestConfig:
    def test_checkpoint_retention_days_default(self):
        """CHECKPOINT_RETENTION_DAYS has a default of 30."""
        from app.config import Settings

        s = Settings()
        assert s.CHECKPOINT_RETENTION_DAYS == 30

    def test_checkpoint_retention_days_env_override(self, monkeypatch):
        """CHECKPOINT_RETENTION_DAYS can be overridden via env var."""
        monkeypatch.setenv("CHECKPOINT_RETENTION_DAYS", "7")
        from importlib import reload
        import app.config as cfg_module
        reload(cfg_module)
        s = cfg_module.Settings()
        assert s.CHECKPOINT_RETENTION_DAYS == 7


# ---------------------------------------------------------------------------
# 8. Background loops — importable and structurally correct
# ---------------------------------------------------------------------------


class TestBackgroundLoops:
    def test_checkpoint_retention_loop_is_coroutine(self):
        """_checkpoint_retention_loop is an async function."""
        import asyncio
        from app.main import _checkpoint_retention_loop

        assert asyncio.iscoroutinefunction(_checkpoint_retention_loop)

    def test_file_watch_trigger_loop_is_coroutine(self):
        """_file_watch_trigger_loop is an async function."""
        import asyncio
        from app.main import _file_watch_trigger_loop

        assert asyncio.iscoroutinefunction(_file_watch_trigger_loop)

    async def test_checkpoint_retention_loop_runs_one_cycle_no_data(self):
        """_checkpoint_retention_loop completes one iteration with no old runs."""
        from app.main import _checkpoint_retention_loop

        # Patch async_session so the loop does nothing and we break after one cycle
        call_count = 0

        @asynccontextmanager
        async def _fake_session():
            db = AsyncMock()
            result = MagicMock()
            result.all.return_value = []  # no old runs
            db.execute = AsyncMock(return_value=result)
            nonlocal call_count
            call_count += 1
            yield db

        with patch("app.main.async_session", new=_fake_session), \
             patch("app.main.settings") as mock_settings, \
             patch("app.main._RETENTION_POLL_INTERVAL", 0):
            mock_settings.CHECKPOINT_RETENTION_DAYS = 30
            # Run loop with a short timeout — it will sleep 0s then query DB
            try:
                await asyncio.wait_for(_checkpoint_retention_loop(), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass  # Expected — loop runs forever

    async def test_file_watch_loop_skips_empty_registrations(self):
        """_file_watch_trigger_loop skips when no file_watch registrations exist."""
        from app.main import _file_watch_trigger_loop

        @asynccontextmanager
        async def _fake_session():
            db = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = []  # no registrations
            db.execute = AsyncMock(return_value=result)
            yield db

        with patch("app.main.async_session", new=_fake_session), \
             patch("app.main._FILE_WATCH_POLL_INTERVAL", 0):
            try:
                await asyncio.wait_for(_file_watch_trigger_loop(), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

    async def test_file_watch_loop_skips_registration_without_event_source(self):
        """_file_watch_trigger_loop skips registrations where event_source is None."""
        from app.main import _file_watch_trigger_loop

        reg = MagicMock()
        reg.id = 1
        reg.procedure_id = "p1"
        reg.version = "1.0"
        reg.event_source = None  # No watch path

        fire_trigger_called = []

        @asynccontextmanager
        async def _fake_session():
            db = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = [reg]
            db.execute = AsyncMock(return_value=result)
            yield db

        with patch("app.main.async_session", new=_fake_session), \
             patch("app.main._FILE_WATCH_POLL_INTERVAL", 0), \
             patch("app.services.trigger_service.fire_trigger",
                   new=AsyncMock(side_effect=lambda *a, **kw: fire_trigger_called.append(True))):
            try:
                await asyncio.wait_for(_file_watch_trigger_loop(), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        # fire_trigger should NOT have been called
        assert fire_trigger_called == []


# ---------------------------------------------------------------------------
# 9. GitHub Actions CI file exists
# ---------------------------------------------------------------------------


class TestCIFile:
    def test_ci_yml_exists(self):
        """CI workflow file exists at .github/workflows/ci.yml."""
        import os

        # Navigate from backend/tests up to workspace root
        here = os.path.dirname(__file__)
        workspace_root = os.path.abspath(os.path.join(here, "..", ".."))
        ci_path = os.path.join(workspace_root, ".github", "workflows", "ci.yml")
        assert os.path.isfile(ci_path), f"CI file not found at {ci_path}"

    def test_ci_yml_has_backend_job(self):
        """CI workflow defines a backend test job."""
        import os
        import yaml  # noqa: F401 — available as pyyaml in requirements

        here = os.path.dirname(__file__)
        workspace_root = os.path.abspath(os.path.join(here, "..", ".."))
        ci_path = os.path.join(workspace_root, ".github", "workflows", "ci.yml")
        with open(ci_path) as f:
            content = f.read()

        assert "backend" in content
        assert "pytest" in content
        assert "frontend" in content


# ---------------------------------------------------------------------------
# 10. LLM usage tracking already implemented — regression guard
# ---------------------------------------------------------------------------


class TestLlmUsageTrackingRegression:
    """Ensure LLM token tracking code is present and not accidentally removed."""

    def test_llm_usage_event_emitted_in_execute_llm_action(self, tmp_path):
        """execute_llm_action source contains llm_usage event emission."""
        import inspect
        from app.runtime import node_executors

        source = inspect.getsource(node_executors.execute_llm_action)
        assert "llm_usage" in source
        assert "prompt_tokens" in source
        assert "completion_tokens" in source
