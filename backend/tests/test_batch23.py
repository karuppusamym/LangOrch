"""Batch 23 tests — compiler validation hardening, circuit breaker dispatch,
LLM cost tracking, and project cost-summary endpoint.

Coverage:
  1. Recursive subflow self-reference detection (validator.py)
  2. Template variable enforcement (validator.py)
  3. Action/channel compatibility check (validator.py)
  4. Circuit breaker agent skip in _find_capable_agent (executor_dispatch.py)
  5. Estimated-cost-usd accumulation in LLM token tracking (node_executors.py)
  6. _MODEL_COST_PER_1K constant sanity (node_executors.py)
  7. GET /api/projects/{id}/cost-summary endpoint (api/projects.py)
  8. get_project_cost_summary service (services/project_service.py)
"""

from __future__ import annotations

import inspect
from contextlib import asynccontextmanager
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ── Helpers ─────────────────────────────────────────────────────


def _make_minimal_ir(procedure_id: str = "test_proc") -> "IRProcedure":
    """Minimal valid IR with one terminate node."""
    from app.compiler.ir import IRNode, IRProcedure, IRTerminatePayload

    return IRProcedure(
        procedure_id=procedure_id,
        version="1.0.0",
        start_node_id="end",
        nodes={
            "end": IRNode(
                node_id="end",
                type="terminate",
                payload=IRTerminatePayload(status="success"),
            )
        },
    )


def _make_sequence_node(
    node_id: str = "seq",
    agent: str | None = None,
    actions: list[str] | None = None,
) -> "IRNode":
    from app.compiler.ir import IRNode, IRSequencePayload, IRStep

    steps = [
        IRStep(step_id=f"s{i}", action=act)
        for i, act in enumerate(actions or ["log"])
    ]
    return IRNode(
        node_id=node_id,
        type="sequence",
        agent=agent,
        payload=IRSequencePayload(steps=steps),
        next_node_id="end",
    )


def _make_subflow_node(node_id: str, subflow_procedure_id: str) -> "IRNode":
    from app.compiler.ir import IRNode, IRSubflowPayload

    return IRNode(
        node_id=node_id,
        type="subflow",
        payload=IRSubflowPayload(procedure_id=subflow_procedure_id, next_node_id="end"),
    )


def _make_agent_mock(
    agent_id: str = "agent1",
    channel: str = "web",
    capabilities: str = "*",
    circuit_open_at: datetime | None = None,
    consecutive_failures: int = 0,
) -> MagicMock:
    agent = MagicMock()
    agent.agent_id = agent_id
    agent.channel = channel
    agent.capabilities = capabilities
    agent.circuit_open_at = circuit_open_at
    agent.consecutive_failures = consecutive_failures
    agent.base_url = "http://agent:9000"
    return agent


# ═══════════════════════════════════════════════════════════════
# 1. Recursive subflow detection
# ═══════════════════════════════════════════════════════════════


class TestRecursiveSubflowDetection:
    """validate_ir should catch subflows that call their own procedure_id."""

    def test_self_referencing_subflow_is_an_error(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSubflowPayload, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="my_proc",
            version="1.0.0",
            start_node_id="sub",
            nodes={
                "sub": IRNode(
                    node_id="sub",
                    type="subflow",
                    payload=IRSubflowPayload(procedure_id="my_proc", next_node_id="end"),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        assert any("self-recurs" in e.lower() or "self_recurs" in e.lower() or "direct self" in e.lower() for e in errors), \
            f"Expected self-recursion error, got: {errors}"

    def test_cross_procedure_subflow_passes(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSubflowPayload, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="parent_proc",
            version="1.0.0",
            start_node_id="sub",
            nodes={
                "sub": IRNode(
                    node_id="sub",
                    type="subflow",
                    payload=IRSubflowPayload(procedure_id="child_proc", next_node_id="end"),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        recur_errors = [e for e in errors if "recurs" in e.lower() or "self" in e.lower()]
        assert recur_errors == [], f"Unexpected recursion errors: {recur_errors}"

    def test_self_recursion_error_mentions_procedure_id(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSubflowPayload, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="acme_pipeline",
            version="2.0.0",
            start_node_id="sub",
            nodes={
                "sub": IRNode(
                    node_id="sub",
                    type="subflow",
                    payload=IRSubflowPayload(procedure_id="acme_pipeline", next_node_id="end"),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        assert any("acme_pipeline" in e for e in errors), \
            f"Expected procedure_id in error message, got: {errors}"


# ═══════════════════════════════════════════════════════════════
# 2. Template variable enforcement
# ═══════════════════════════════════════════════════════════════


class TestTemplateVariableEnforcement:
    """validate_ir should flag undeclared {{ var }} references when schema is declared."""

    def _make_ir_with_step_params(
        self,
        params: dict,
        schema: dict | None = None,
    ) -> "IRProcedure":
        from app.compiler.ir import (
            IRNode, IRProcedure, IRSequencePayload, IRStep, IRTerminatePayload,
        )
        return IRProcedure(
            procedure_id="tpl_proc",
            version="1.0.0",
            variables_schema=schema or {"declared_var": {"type": "string"}},
            start_node_id="seq",
            nodes={
                "seq": IRNode(
                    node_id="seq",
                    type="sequence",
                    agent="my_agent",
                    next_node_id="end",
                    payload=IRSequencePayload(
                        steps=[IRStep(step_id="s1", action="log", params=params)]
                    ),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=__import__("app.compiler.ir", fromlist=["IRTerminatePayload"]).IRTerminatePayload(status="success"),
                ),
            },
        )

    def test_undeclared_template_var_in_params_is_error(self):
        from app.compiler.validator import validate_ir

        ir = self._make_ir_with_step_params({"message": "Hello {{ undeclared_xyz }}"})
        errors = validate_ir(ir)
        assert any("undeclared_xyz" in e for e in errors), f"Expected template var error, got: {errors}"

    def test_declared_template_var_passes(self):
        from app.compiler.validator import validate_ir

        ir = self._make_ir_with_step_params({"message": "Hello {{ declared_var }}"})
        errors = validate_ir(ir)
        template_errors = [e for e in errors if "declared_var" in e]
        assert template_errors == [], f"Unexpected template error for declared_var: {template_errors}"

    def test_implicit_run_id_var_passes(self):
        from app.compiler.validator import validate_ir

        ir = self._make_ir_with_step_params({"message": "Run {{ run_id }}"})
        errors = validate_ir(ir)
        template_errors = [e for e in errors if "run_id" in e]
        assert template_errors == [], f"Unexpected template error for run_id: {template_errors}"

    def test_empty_schema_skips_enforcement(self):
        """When variables_schema is empty, template checks are skipped."""
        from app.compiler.ir import (
            IRNode, IRProcedure, IRSequencePayload, IRStep, IRTerminatePayload,
        )
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="no_schema_proc",
            version="1.0.0",
            variables_schema={},  # empty — skip enforcement
            start_node_id="seq",
            nodes={
                "seq": IRNode(
                    node_id="seq",
                    type="sequence",
                    agent="my_agent",
                    next_node_id="end",
                    payload=IRSequencePayload(
                        steps=[IRStep(step_id="s1", action="log", params={"message": "{{ mystery_var }}"})]
                    ),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        template_errors = [e for e in errors if "mystery_var" in e]
        assert template_errors == [], f"Empty schema should skip template check, got: {template_errors}"


# ═══════════════════════════════════════════════════════════════
# 3. Action / channel compatibility
# ═══════════════════════════════════════════════════════════════


class TestActionChannelCompatibility:
    """validate_ir warns when a sequence node has non-internal steps but no agent."""

    def test_non_internal_action_without_agent_is_error(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSequencePayload, IRStep, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="no_agent_proc",
            version="1.0.0",
            start_node_id="seq",
            nodes={
                "seq": IRNode(
                    node_id="seq",
                    type="sequence",
                    agent=None,  # no agent
                    next_node_id="end",
                    payload=IRSequencePayload(
                        steps=[IRStep(step_id="s1", action="click_button")]  # not internal
                    ),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        assert any("click_button" in e for e in errors), \
            f"Expected action/channel error for click_button, got: {errors}"

    def test_non_internal_action_with_agent_passes(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSequencePayload, IRStep, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="with_agent_proc",
            version="1.0.0",
            start_node_id="seq",
            nodes={
                "seq": IRNode(
                    node_id="seq",
                    type="sequence",
                    agent="WEB",  # agent declared
                    next_node_id="end",
                    payload=IRSequencePayload(
                        steps=[IRStep(step_id="s1", action="click_button")]
                    ),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        compat_errors = [e for e in errors if "click_button" in e]
        assert compat_errors == [], f"Should not error when agent is set: {compat_errors}"

    def test_internal_action_without_agent_passes(self):
        from app.compiler.ir import IRNode, IRProcedure, IRSequencePayload, IRStep, IRTerminatePayload
        from app.compiler.validator import validate_ir

        ir = IRProcedure(
            procedure_id="internal_proc",
            version="1.0.0",
            start_node_id="seq",
            nodes={
                "seq": IRNode(
                    node_id="seq",
                    type="sequence",
                    agent=None,
                    next_node_id="end",
                    payload=IRSequencePayload(
                        steps=[IRStep(step_id="s1", action="log")]  # internal action
                    ),
                ),
                "end": IRNode(
                    node_id="end",
                    type="terminate",
                    payload=IRTerminatePayload(status="success"),
                ),
            },
        )
        errors = validate_ir(ir)
        compat_errors = [e for e in errors if "log" in e and "action" in e.lower()]
        assert compat_errors == [], f"Internal action 'log' should not trigger channel error: {compat_errors}"


# ═══════════════════════════════════════════════════════════════
# 4. Circuit breaker agent skip
# ═══════════════════════════════════════════════════════════════


class TestCircuitBreakerDispatch:
    """_find_capable_agent should skip agents whose circuit is currently open."""

    @pytest.mark.asyncio
    async def test_circuit_open_agent_is_skipped(self):
        from app.runtime.executor_dispatch import _find_capable_agent

        # Agent with circuit opened 60 seconds ago (well within reset window of 300s)
        open_time = datetime.now(timezone.utc) - timedelta(seconds=60)
        agent = _make_agent_mock(circuit_open_at=open_time)

        db = AsyncMock()
        db.execute = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [agent]
        db.execute.return_value = result_mock

        found = await _find_capable_agent(db, "web", "click_button")
        assert found is None, "Circuit-open agent should be skipped"

    @pytest.mark.asyncio
    async def test_circuit_expired_agent_is_returned(self):
        """Agent whose circuit opened >300s ago should be considered available."""
        from app.runtime.executor_dispatch import _find_capable_agent

        # Circuit opened 400 seconds ago — past the 300s reset threshold
        old_time = datetime.now(timezone.utc) - timedelta(seconds=400)
        agent = _make_agent_mock(circuit_open_at=old_time)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [agent]
        db.execute.return_value = result_mock

        found = await _find_capable_agent(db, "web", "click_button")
        assert found is agent, "Expired circuit agent should be returned"

    @pytest.mark.asyncio
    async def test_healthy_agent_returned(self):
        from app.runtime.executor_dispatch import _find_capable_agent

        agent = _make_agent_mock(circuit_open_at=None)

        db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalars.return_value.all.return_value = [agent]
        db.execute.return_value = result_mock

        found = await _find_capable_agent(db, "web", "click_button")
        assert found is agent


# ═══════════════════════════════════════════════════════════════
# 5. Estimated cost USD — model constant
# ═══════════════════════════════════════════════════════════════


class TestModelCostTable:
    """_MODEL_COST_PER_1K should contain well-known models with prompt/completion rates."""

    def test_cost_table_has_gpt4(self):
        from app.runtime.node_executors import _MODEL_COST_PER_1K
        assert "gpt-4" in _MODEL_COST_PER_1K

    def test_all_entries_have_prompt_and_completion_keys(self):
        from app.runtime.node_executors import _MODEL_COST_PER_1K
        for model, rates in _MODEL_COST_PER_1K.items():
            assert "prompt" in rates, f"Model {model} missing 'prompt' rate"
            assert "completion" in rates, f"Model {model} missing 'completion' rate"

    def test_cost_calculation_is_positive(self):
        from app.runtime.node_executors import _MODEL_COST_PER_1K
        rates = _MODEL_COST_PER_1K["gpt-4"]
        cost = (1000 * rates["prompt"] + 500 * rates["completion"]) / 1000.0
        assert cost > 0


# ═══════════════════════════════════════════════════════════════
# 6. Run model + schema have estimated_cost_usd
# ═══════════════════════════════════════════════════════════════


class TestEstimatedCostSchema:
    def test_run_orm_model_has_estimated_cost_column(self):
        from app.db.models import Run
        assert hasattr(Run, "estimated_cost_usd"), "Run ORM model missing estimated_cost_usd"

    def test_run_out_schema_has_estimated_cost_field(self):
        from app.schemas.runs import RunOut
        fields = RunOut.model_fields
        assert "estimated_cost_usd" in fields

    def test_run_out_estimated_cost_is_optional_float(self):
        from app.schemas.runs import RunOut
        field = RunOut.model_fields["estimated_cost_usd"]
        # default should be None
        assert field.default is None or field.is_required() is False


# ═══════════════════════════════════════════════════════════════
# 7. Project cost-summary service
# ═══════════════════════════════════════════════════════════════


class TestProjectCostSummaryService:
    @pytest.mark.asyncio
    async def test_cost_summary_returns_expected_keys(self):
        from app.services.project_service import get_project_cost_summary

        db = AsyncMock()
        row_mock = MagicMock()
        row_mock.run_count = 5
        row_mock.total_prompt_tokens = 12000
        row_mock.total_completion_tokens = 4000
        row_mock.estimated_cost_usd = 0.84
        result_mock = MagicMock()
        result_mock.one.return_value = row_mock
        db.execute = AsyncMock(return_value=result_mock)

        summary = await get_project_cost_summary(db, "proj1", period_days=30)
        assert summary["project_id"] == "proj1"
        assert summary["run_count"] == 5
        assert summary["total_prompt_tokens"] == 12000
        assert summary["total_completion_tokens"] == 4000
        assert summary["estimated_cost_usd"] == pytest.approx(0.84, rel=1e-4)
        assert summary["period_days"] == 30

    @pytest.mark.asyncio
    async def test_cost_summary_handles_none_values(self):
        from app.services.project_service import get_project_cost_summary

        db = AsyncMock()
        row_mock = MagicMock()
        row_mock.run_count = 0
        row_mock.total_prompt_tokens = None
        row_mock.total_completion_tokens = None
        row_mock.estimated_cost_usd = None
        result_mock = MagicMock()
        result_mock.one.return_value = row_mock
        db.execute = AsyncMock(return_value=result_mock)

        summary = await get_project_cost_summary(db, "empty_proj")
        assert summary["total_prompt_tokens"] == 0
        assert summary["total_completion_tokens"] == 0
        assert summary["estimated_cost_usd"] == 0.0
        assert summary["run_count"] == 0

    def test_cost_summary_function_exists_in_project_service(self):
        from app.services import project_service
        assert hasattr(project_service, "get_project_cost_summary")
        assert asyncio_iscoroutinefunction(project_service.get_project_cost_summary)


# ═══════════════════════════════════════════════════════════════
# 8. Project cost-summary API endpoint
# ═══════════════════════════════════════════════════════════════


class TestProjectCostSummaryAPI:
    def test_cost_summary_endpoint_exists_in_projects_router(self):
        from app.api.projects import router
        routes = [r.path for r in router.routes]  # type: ignore[attr-defined]
        assert any("cost-summary" in p for p in routes), \
            f"cost-summary route not found in {routes}"

    def test_cost_summary_endpoint_has_correct_method(self):
        from app.api.projects import router
        for route in router.routes:  # type: ignore[attr-defined]
            if hasattr(route, "path") and "cost-summary" in route.path:
                assert "GET" in route.methods, "cost-summary should be GET"
                return
        pytest.fail("cost-summary route not found")

    @pytest.mark.asyncio
    async def test_cost_summary_returns_404_for_missing_project(self):
        from fastapi.testclient import TestClient
        from app.main import app

        with patch("app.services.project_service.get_project", new=AsyncMock(return_value=None)):
            client = TestClient(app)
            resp = client.get("/api/projects/nonexistent_proj/cost-summary")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_cost_summary_returns_data_for_existing_project(self):
        from fastapi.testclient import TestClient
        from app.main import app
        from app.db.models import Project

        mock_proj = MagicMock(spec=Project)
        mock_proj.project_id = "proj_abc"
        mock_proj.name = "Test Project"
        mock_proj.description = None

        mock_summary = {
            "project_id": "proj_abc",
            "period_days": 30,
            "run_count": 3,
            "total_prompt_tokens": 5000,
            "total_completion_tokens": 2000,
            "estimated_cost_usd": 0.21,
        }

        with patch("app.services.project_service.get_project", new=AsyncMock(return_value=mock_proj)), \
             patch("app.services.project_service.get_project_cost_summary", new=AsyncMock(return_value=mock_summary)):
            client = TestClient(app)
            resp = client.get("/api/projects/proj_abc/cost-summary")

        assert resp.status_code == 200
        data = resp.json()
        assert data["project_id"] == "proj_abc"
        assert data["run_count"] == 3
        assert "estimated_cost_usd" in data


# ═══════════════════════════════════════════════════════════════
# 9. Validator integration (parse → validate roundtrip)
# ═══════════════════════════════════════════════════════════════


class TestValidatorIntegration:
    def test_parse_and_validate_ckp_with_template_violation(self):
        from app.compiler.parser import parse_ckp
        from app.compiler.validator import validate_ir

        ckp = {
            "procedure_id": "tpl_viol_proc",
            "version": "1.0.0",
            "variables_schema": {"declared_only": {"type": "string"}},
            "workflow_graph": {
                "start_node": "seq",
                "nodes": {
                    "seq": {
                        "type": "sequence",
                        "agent": "TEST",
                        "next_node": "end",
                        "steps": [
                            {
                                "step_id": "s1",
                                "action": "log",
                                "message": "value is {{ undeclared_thing }}",
                            }
                        ],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("undeclared_thing" in e for e in errors), \
            f"Expected template violation, got: {errors}"

    def test_parse_and_validate_ckp_with_valid_template(self):
        from app.compiler.parser import parse_ckp
        from app.compiler.validator import validate_ir

        ckp = {
            "procedure_id": "tpl_ok_proc",
            "version": "1.0.0",
            "variables_schema": {"product_name": {"type": "string"}},
            "workflow_graph": {
                "start_node": "seq",
                "nodes": {
                    "seq": {
                        "type": "sequence",
                        "agent": "TEST",
                        "next_node": "end",
                        "steps": [
                            {
                                "step_id": "s1",
                                "action": "log",
                                "message": "name is {{ product_name }}, run {{ run_id }}",
                            }
                        ],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        template_errors = [e for e in errors if "undeclared" in e.lower() or "template" in e.lower()]
        assert template_errors == [], f"Valid template should produce no errors, got: {template_errors}"


# ── Utility to check coroutine functions ────────────────────────

def asyncio_iscoroutinefunction(func) -> bool:
    return inspect.iscoroutinefunction(func)
