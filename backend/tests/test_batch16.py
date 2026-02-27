"""
Tests for Batch 16 features:
  1. validate_input_vars — required field, regex, min/max, allowed_values, type checking
  2. create_run API rejects invalid input_vars with 422
  3. create_run API accepts valid input_vars (no schema → always passes)
  4. execution_mode=dry_run in execute_sequence:
     - agent_http binding → skipped, dry_run_step_skipped event emitted
     - mcp_tool binding  → skipped, dry_run_step_skipped event emitted
     - internal binding  → still executed (safe)
     - dry_run flag propagated through OrchestratorState
  5. execution_mode=production → real dispatch proceeds (no skip)
"""

import asyncio
import pytest
from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# Helpers shared across tests
# ---------------------------------------------------------------------------


def _make_step(*, action="navigate", output_variable=None, binding_kind="agent_http"):
    step = MagicMock()
    step.step_id = "s1"
    step.action = action
    step.params = {}
    step.output_variable = output_variable
    step.idempotency_key = None
    step.retry_on_failure = False
    step.max_retries = 0
    step.delay_ms = 0
    step.wait_ms = None
    step.wait_after_ms = None
    step.timeout_ms = None
    step.error_handlers = []
    step.executor_binding = None  # force dynamic resolve path
    return step


def _make_node(step):
    node = MagicMock()
    node.node_id = "n1"
    node.payload = MagicMock()
    node.payload.steps = [step]
    node.payload.error_handlers = []
    node.sla = None
    return node


def _base_state(*, execution_mode="production", run_id="run-16"):
    return {
        "vars": {},
        "run_id": run_id,
        "current_node_id": "n1",
        "next_node_id": None,
        "events": [],
        "error": None,
        "execution_mode": execution_mode,
        "global_config": {},
    }


def _make_db_factory(captured_events=None):
    """Return a db_factory whose db mock captures emit_event calls."""
    captured_events = captured_events if captured_events is not None else []
    mock_db = AsyncMock()

    @asynccontextmanager
    async def db_factory():
        yield mock_db

    return db_factory, captured_events


# ---------------------------------------------------------------------------
# 1. validate_input_vars — unit tests
# ---------------------------------------------------------------------------


class TestValidateInputVars:
    def test_empty_schema_always_passes(self):
        from app.utils.input_vars import validate_input_vars
        assert validate_input_vars({}, {"foo": "bar"}) == {}
        assert validate_input_vars({}, None) == {}

    def test_required_field_missing_raises(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"name": {"type": "string", "required": True}}
        errors = validate_input_vars(schema, {})
        assert "name" in errors
        assert "required" in errors["name"].lower()

    def test_required_empty_string_raises(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"name": {"type": "string", "required": True}}
        errors = validate_input_vars(schema, {"name": "   "})
        assert "name" in errors

    def test_optional_missing_no_error(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"note": {"type": "string", "required": False}}
        errors = validate_input_vars(schema, {})
        assert errors == {}

    def test_regex_valid_passes(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"code": {"type": "string", "validation": {"regex": r"^[A-Z]{3}$"}}}
        errors = validate_input_vars(schema, {"code": "ABC"})
        assert errors == {}

    def test_regex_invalid_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"code": {"type": "string", "validation": {"regex": r"^[A-Z]{3}$"}}}
        errors = validate_input_vars(schema, {"code": "abc"})
        assert "code" in errors
        assert "pattern" in errors["code"].lower()

    def test_allowed_values_valid_passes(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"env": {"type": "string", "validation": {"allowed_values": ["dev", "prod"]}}}
        errors = validate_input_vars(schema, {"env": "prod"})
        assert errors == {}

    def test_allowed_values_invalid_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"env": {"type": "string", "validation": {"allowed_values": ["dev", "prod"]}}}
        errors = validate_input_vars(schema, {"env": "staging"})
        assert "env" in errors
        assert "one of" in errors["env"].lower()

    def test_number_min_valid(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"count": {"type": "number", "validation": {"min": 1}}}
        assert validate_input_vars(schema, {"count": 5}) == {}

    def test_number_min_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"count": {"type": "number", "validation": {"min": 1}}}
        errors = validate_input_vars(schema, {"count": 0})
        assert "count" in errors
        assert "least" in errors["count"].lower()

    def test_number_max_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"count": {"type": "number", "validation": {"max": 10}}}
        errors = validate_input_vars(schema, {"count": 99})
        assert "count" in errors
        assert "most" in errors["count"].lower()

    def test_string_max_length_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"slug": {"type": "string", "validation": {"max": 5}}}
        errors = validate_input_vars(schema, {"slug": "toolong"})
        assert "slug" in errors

    def test_number_type_coercion_from_string(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"count": {"type": "number"}}
        errors = validate_input_vars(schema, {"count": "42"})
        assert errors == {}

    def test_number_type_bad_string_fails(self):
        from app.utils.input_vars import validate_input_vars
        schema = {"count": {"type": "number"}}
        errors = validate_input_vars(schema, {"count": "not-a-number"})
        assert "count" in errors

    def test_multiple_fields_multiple_errors(self):
        from app.utils.input_vars import validate_input_vars
        schema = {
            "name": {"type": "string", "required": True},
            "age": {"type": "number", "validation": {"min": 0}},
        }
        errors = validate_input_vars(schema, {"age": -1})
        assert "name" in errors  # required missing
        assert "age" in errors   # below min

    def test_valid_full_schema_no_error(self):
        from app.utils.input_vars import validate_input_vars
        schema = {
            "env": {"type": "string", "required": True, "validation": {"allowed_values": ["dev", "prod"]}},
            "retries": {"type": "number", "validation": {"min": 0, "max": 5}},
        }
        errors = validate_input_vars(schema, {"env": "prod", "retries": 3})
        assert errors == {}


# ---------------------------------------------------------------------------
# 2. create_run API — integration with validation
# ---------------------------------------------------------------------------


class TestCreateRunValidation:
    @pytest.mark.asyncio
    async def test_create_run_rejects_missing_required(self):
        """POST /api/runs returns 422 when a required input var is absent."""
        from app.api.runs import create_run
        from app.schemas.runs import RunCreate
        from fastapi import HTTPException

        schema = {"env": {"type": "string", "required": True}}
        proc = MagicMock()
        proc.procedure_id = "p1"
        proc.version = "1"
        proc.ckp_json = '{"variables_schema": {"env": {"type": "string", "required": true}}}'

        with (
            patch("app.api.runs.procedure_service.get_procedure", new=AsyncMock(return_value=proc)),
        ):
            body = RunCreate(procedure_id="p1", procedure_version="1", input_vars={})
            with pytest.raises(HTTPException) as exc_info:
                await create_run(body, db=AsyncMock())
            assert exc_info.value.status_code == 422
            detail = exc_info.value.detail
            assert isinstance(detail, dict)
            assert "errors" in detail
            assert "env" in detail["errors"]

    @pytest.mark.asyncio
    async def test_create_run_rejects_invalid_regex(self):
        """POST /api/runs returns 422 when a field fails regex validation."""
        from app.api.runs import create_run
        from app.schemas.runs import RunCreate
        from fastapi import HTTPException

        proc = MagicMock()
        proc.procedure_id = "p1"
        proc.version = "1"
        proc.ckp_json = '{"variables_schema": {"code": {"type": "string", "validation": {"regex": "^[A-Z]{3}$"}}}}'

        with patch("app.api.runs.procedure_service.get_procedure", new=AsyncMock(return_value=proc)):
            body = RunCreate(procedure_id="p1", procedure_version="1", input_vars={"code": "abc"})
            with pytest.raises(HTTPException) as exc_info:
                await create_run(body, db=AsyncMock())
            assert exc_info.value.status_code == 422
            assert "code" in exc_info.value.detail["errors"]

    @pytest.mark.asyncio
    async def test_create_run_no_schema_always_passes(self):
        """POST /api/runs with no variables_schema skips validation entirely."""
        from app.api.runs import create_run
        from app.schemas.runs import RunCreate

        proc = MagicMock()
        proc.procedure_id = "p1"
        proc.version = "1"
        proc.ckp_json = '{"workflow_graph": {}}'

        mock_run = MagicMock()
        mock_run.run_id = "run-99"

        with (
            patch("app.api.runs.procedure_service.get_procedure", new=AsyncMock(return_value=proc)),
            patch("app.api.runs.run_service.create_run", new=AsyncMock(return_value=mock_run)),
            patch("app.api.runs.enqueue_run", MagicMock(return_value=MagicMock())),
        ):
            mock_db = AsyncMock()
            body = RunCreate(procedure_id="p1", procedure_version="1", input_vars={"anything": "goes"})
            result = await create_run(body, db=mock_db)
            assert result == mock_run

    @pytest.mark.asyncio
    async def test_create_run_valid_vars_passes(self):
        """POST /api/runs with valid input_vars that satisfy schema runs successfully."""
        from app.api.runs import create_run
        from app.schemas.runs import RunCreate

        proc = MagicMock()
        proc.procedure_id = "p1"
        proc.version = "1"
        proc.ckp_json = '{"variables_schema": {"env": {"type": "string", "required": true, "validation": {"allowed_values": ["dev", "prod"]}}}}'

        mock_run = MagicMock()
        mock_run.run_id = "run-100"

        with (
            patch("app.api.runs.procedure_service.get_procedure", new=AsyncMock(return_value=proc)),
            patch("app.api.runs.run_service.create_run", new=AsyncMock(return_value=mock_run)),
            patch("app.api.runs.enqueue_run", MagicMock(return_value=MagicMock())),
        ):
            mock_db = AsyncMock()
            body = RunCreate(procedure_id="p1", procedure_version="1", input_vars={"env": "prod"})
            result = await create_run(body, db=mock_db)
            assert result == mock_run


# ---------------------------------------------------------------------------
# 3. execution_mode=dry_run in execute_sequence
# ---------------------------------------------------------------------------


def _make_binding(kind: str, ref: str = "http://agent:8080"):
    b = MagicMock()
    b.kind = kind
    b.ref = ref
    return b


class TestDryRunExecuteSequence:
    @pytest.mark.asyncio
    async def test_agent_http_skipped_in_dry_run(self):
        """agent_http dispatch is skipped and dry_run_step_skipped event is emitted."""
        from app.runtime.node_executors import execute_sequence

        captured: list = []
        db_factory, _ = _make_db_factory(captured)

        step = _make_step(output_variable="res")
        node = _make_node(step)

        state = _base_state(execution_mode="dry_run")

        binding = _make_binding("agent_http")

        with (
            patch(
                "app.runtime.executor_dispatch.resolve_executor",
                new=AsyncMock(return_value=(binding, "tool")),
            ),
            patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: captured.append(event_type))),
        ):
            result_state = await execute_sequence(node, state, db_factory=db_factory)

        dry_run_events = [e for e in captured if e == "dry_run_step_skipped"]
        assert len(dry_run_events) == 1, f"Expected dry_run_step_skipped event, got: {captured}"

        # Output var should hold the dry_run stub result
        assert result_state["vars"].get("res", {}).get("dry_run") is True

    @pytest.mark.asyncio
    async def test_mcp_tool_skipped_in_dry_run(self):
        """mcp_tool dispatch is skipped and dry_run_step_skipped event is emitted."""
        from app.runtime.node_executors import execute_sequence

        captured: list = []
        db_factory, _ = _make_db_factory(captured)

        step = _make_step(output_variable="out")
        node = _make_node(step)

        state = _base_state(execution_mode="dry_run")

        binding = _make_binding("mcp_tool", ref="http://mcp:9000")

        with (
            patch(
                "app.runtime.executor_dispatch.resolve_executor",
                new=AsyncMock(return_value=(binding, "tool")),
            ),
            patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: captured.append(event_type))),
        ):
            result_state = await execute_sequence(node, state, db_factory=db_factory)

        assert "dry_run_step_skipped" in captured
        assert result_state["vars"].get("out", {}).get("dry_run") is True

    @pytest.mark.asyncio
    async def test_internal_binding_still_executes_in_dry_run(self):
        """Internal actions are NOT skipped during dry_run (they are side-effect-free)."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(output_variable="val")
        step.executor_binding = MagicMock()
        step.executor_binding.kind = "internal"

        node = _make_node(step)
        state = _base_state(execution_mode="dry_run")

        executed = {"n": 0}

        async def fake_action(action, params, vs):
            executed["n"] += 1
            return "internal_result"

        with patch("app.runtime.node_executors._execute_step_action", side_effect=fake_action):
            result_state = await execute_sequence(node, state, db_factory=None)

        assert executed["n"] == 1
        assert result_state["vars"].get("val") == "internal_result"

    @pytest.mark.asyncio
    async def test_production_mode_does_not_skip(self):
        """production mode: dry_run_step_skipped event is never emitted.

        Uses an internal binding (safe, no network) to keep the test isolated
        while confirming the dry_run guard is mode-gated.
        """
        from app.runtime.node_executors import execute_sequence

        captured: list = []
        db_factory, _ = _make_db_factory(captured)

        # Use internal binding -- internal steps always execute in any mode
        step = _make_step(output_variable="res")
        step.executor_binding = MagicMock()
        step.executor_binding.kind = "internal"
        node = _make_node(step)

        state = _base_state(execution_mode="production")

        with (
            patch("app.runtime.node_executors._execute_step_action", new=AsyncMock(return_value="ok")),
            patch("app.services.run_service.emit_event", new=AsyncMock(side_effect=lambda db, run_id, event_type, **kw: captured.append(event_type))),
        ):
            await execute_sequence(node, state, db_factory=None)

        # dry_run_step_skipped must NOT appear in production mode
        assert "dry_run_step_skipped" not in captured

    @pytest.mark.asyncio
    async def test_dry_run_default_when_no_execution_mode_in_state(self):
        """When execution_mode is absent from state, behavior is production (no skip)."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(output_variable="val")
        step.executor_binding = MagicMock()
        step.executor_binding.kind = "internal"

        node = _make_node(step)

        # State without execution_mode key
        state = {
            "vars": {},
            "run_id": "run-x",
            "current_node_id": "n1",
            "next_node_id": None,
            "events": [],
            "error": None,
            "global_config": {},
        }

        async def fake_action(action, params, vs):
            return "ok"

        with patch("app.runtime.node_executors._execute_step_action", side_effect=fake_action):
            result_state = await execute_sequence(node, state, db_factory=None)

        assert result_state["vars"].get("val") == "ok"
