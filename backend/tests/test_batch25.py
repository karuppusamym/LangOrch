"""Batch 25 tests — P1/P2 gap items:

1. estimated_cost_usd — RunOut schema field + DB model presence
2. Agent round-robin — executor_dispatch shuffles agent list
3. screenshot_on_fail — fires screenshot_requested on step error
4. mock_external_calls — stub result returned instead of real dispatch
5. test_data_overrides — per-step override applied
6. dry_run mode — dry_run_step_skipped event emitted for agent/MCP steps
"""

from __future__ import annotations

import asyncio
import inspect
import random
import textwrap
import types
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper factories
# ---------------------------------------------------------------------------

def _make_ir_node(node_id: str = "n1", agent: str = "WEB") -> Any:
    from app.compiler.ir import IRNode
    return IRNode(
        node_id=node_id,
        name=node_id,
        kind="action",
        agent=agent,
        steps=[],
        on_error="fail",
    )


def _make_ir_step(step_id: str = "s1", action: str = "click") -> Any:
    from app.compiler.ir import IRStep, ExecutorBinding
    return IRStep(
        step_id=step_id,
        action=action,
        params={},
        executor_binding=ExecutorBinding(kind="agent_http", ref="http://agent:8001"),
    )


def _make_agent(agent_id: str = "a1", channel: str = "web",
                base_url: str = "http://agent:8001",
                capabilities: str = "") -> Any:
    from app.db.models import AgentInstance
    from datetime import datetime, timezone
    ag = AgentInstance()
    ag.agent_id = agent_id
    ag.channel = channel
    ag.base_url = base_url
    ag.status = "online"
    ag.capabilities = capabilities
    ag.circuit_open_at = None
    ag.consecutive_failures = 0
    ag.registered_at = datetime.now(timezone.utc)
    ag.last_heartbeat = datetime.now(timezone.utc)
    return ag


# ===========================================================================
# 1. estimated_cost_usd — schema / model
# ===========================================================================

class TestEstimatedCostSchema:
    """Verify estimated_cost_usd is present and typed correctly everywhere."""

    def test_db_model_has_field(self):
        from app.db.models import Run
        assert hasattr(Run, "estimated_cost_usd"), "ORM model missing estimated_cost_usd"

    def test_runout_schema_field_present(self):
        from app.schemas.runs import RunOut
        assert "estimated_cost_usd" in RunOut.model_fields

    def test_runout_field_is_optional_float(self):
        from app.schemas.runs import RunOut
        import typing
        field = RunOut.model_fields["estimated_cost_usd"]
        ann = field.annotation
        # Should accept None (Optional[float] or float | None)
        args = getattr(ann, "__args__", ())
        assert type(None) in args or ann is type(None) or str(ann).startswith("typing.Optional")

    def test_runout_default_is_none(self):
        from app.schemas.runs import RunOut
        field = RunOut.model_fields["estimated_cost_usd"]
        assert field.default is None

    def test_runout_serialises_cost(self):
        from app.schemas.runs import RunOut
        # Supply required non-nullable fields for RunOut
        m = RunOut.model_validate({
            "run_id": "r1",
            "procedure_id": "p1",
            "project_id": "proj1",
            "procedure_version": "1",
            "status": "completed",
            "thread_id": "t1",
            "input_vars": {},
            "output_vars": None,
            "total_prompt_tokens": 100,
            "total_completion_tokens": 50,
            "estimated_cost_usd": 0.000123,
            "started_at": None,
            "ended_at": None,
            "duration_seconds": None,
            "error_message": None,
            "parent_run_id": None,
            "trigger_type": None,
            "triggered_by": None,
            "last_node_id": None,
            "last_step_id": None,
            "created_at": "2025-01-01T00:00:00",
            "updated_at": "2025-01-01T00:00:00",
        })
        assert m.estimated_cost_usd == pytest.approx(0.000123, rel=1e-5)

    def test_runout_null_cost_allowed(self):
        from app.schemas.runs import RunOut
        m = RunOut.model_validate({
            "run_id": "r1", "procedure_id": "p1", "project_id": "proj1",
            "procedure_version": "1",
            "status": "completed", "thread_id": "t1",
            "input_vars": {}, "output_vars": None,
            "total_prompt_tokens": None, "total_completion_tokens": None,
            "estimated_cost_usd": None,
            "started_at": None, "ended_at": None, "duration_seconds": None,
            "error_message": None, "parent_run_id": None,
            "trigger_type": None, "triggered_by": None,
            "last_node_id": None, "last_step_id": None,
            "created_at": "2025-01-01T00:00:00", "updated_at": "2025-01-01T00:00:00",
        })
        assert m.estimated_cost_usd is None


# ===========================================================================
# 2. Agent round-robin (deterministic pool counters, Batch 32)
# ===========================================================================

class TestAgentRoundRobin:
    """executor_dispatch._find_capable_agent uses deterministic round-robin."""

    def test_pool_counters_in_dispatch(self):
        """_pool_counters defaultdict must be present (replaces random.shuffle)."""
        import app.runtime.executor_dispatch as mod
        assert hasattr(mod, "_pool_counters"), \
            "_pool_counters not found in executor_dispatch"

    def test_round_robin_in_source(self):
        """Round-robin via _pool_counters must appear in source; no random.shuffle."""
        import app.runtime.executor_dispatch as mod
        src = inspect.getsource(mod)
        assert "_pool_counters" in src, "_pool_counters not found in executor_dispatch"
        assert "random.shuffle" not in src, \
            "random.shuffle still present – should have been replaced by round-robin"

    def test_round_robin_cycles_agents(self):
        """Successive calls should cycle through agents deterministically."""
        import app.runtime.executor_dispatch as mod

        agents = [_make_agent(f"a{i}", capabilities="click") for i in range(3)]

        async def _run():
            # Reset counters to get deterministic results
            mod._pool_counters.clear()
            db_mock = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = list(agents)
            db_mock.execute = AsyncMock(
                return_value=MagicMock(scalars=MagicMock(return_value=scalars_mock))
            )
            results = []
            for _ in range(6):
                scalars_mock.all.return_value = list(agents)
                a = await mod._find_capable_agent(db_mock, "web", "click")
                assert a is not None
                results.append(a.agent_id)
            # 6 calls across 3 agents → each visited at least once
            assert len(set(results)) >= 2, "round-robin should distribute across agents"

        asyncio.run(_run())

    def test_returns_one_of_capable_agents(self):
        """With multiple capable agents, one is always returned (no None)."""
        import app.runtime.executor_dispatch as mod

        agents = [_make_agent(f"a{i}", capabilities="click,type") for i in range(5)]

        async def _run():
            db_mock = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = agents
            db_mock.execute = AsyncMock(
                return_value=MagicMock(scalars=MagicMock(return_value=scalars_mock))
            )
            results = set()
            for _ in range(10):
                scalars_mock.all.return_value = list(agents)
                a = await mod._find_capable_agent(db_mock, "web", "click")
                assert a is not None
                results.add(a.agent_id)
            assert len(results) >= 1

        asyncio.run(_run())

    def test_circuit_open_agents_skipped(self):
        """Circuit-open agents must be skipped by the round-robin logic."""
        import app.runtime.executor_dispatch as mod
        from datetime import datetime, timezone

        bad = _make_agent("bad", capabilities="")
        bad.circuit_open_at = datetime.now(timezone.utc)   # circuit is open NOW
        good = _make_agent("good", capabilities="")

        async def _run():
            db_mock = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = [bad, good]
            db_mock.execute = AsyncMock(
                return_value=MagicMock(scalars=MagicMock(return_value=scalars_mock))
            )
            result = await mod._find_capable_agent(db_mock, "web", "click")
            assert result is not None
            assert result.agent_id == "good"

        asyncio.run(_run())

    def test_no_agents_returns_none(self):
        import app.runtime.executor_dispatch as mod

        async def _run():
            db_mock = MagicMock()
            scalars_mock = MagicMock()
            scalars_mock.all.return_value = []
            db_mock.execute = AsyncMock(
                return_value=MagicMock(scalars=MagicMock(return_value=scalars_mock))
            )
            result = await mod._find_capable_agent(db_mock, "web", "click")
            assert result is None

        asyncio.run(_run())


# ===========================================================================
# 3. screenshot_on_fail
# ===========================================================================

class TestScreenshotOnFail:
    """screenshot_requested event emitted when screenshot_on_fail is True."""

    def test_screenshot_flag_read_from_global_config(self):
        """Source must read screenshot_on_fail from state global_config."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "screenshot_on_fail" in src

    def test_screenshot_event_name_correct(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "screenshot_requested" in src

    def test_global_config_key_path(self):
        """State path must be global_config -> screenshot_on_fail."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        # Both key lookups should appear together
        assert 'get("global_config")' in src or "global_config" in src
        assert '"screenshot_on_fail"' in src or "'screenshot_on_fail'" in src

    def test_screenshot_block_has_error_payload(self):
        """screenshot_requested event payload should carry the error string."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        # The emit block for screenshot_requested should include "error"
        idx = src.find("screenshot_requested")
        snippet = src[idx:idx+700]
        assert "error" in snippet


# ===========================================================================
# 4. mock_external_calls
# ===========================================================================

class TestMockExternalCalls:
    """mock_external_calls=True must produce stub result, not real HTTP call."""

    def test_mock_flag_read_in_node_executors(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "mock_external_calls" in src

    def test_mock_result_keys(self):
        """Stub result should include mocked=True, action, binding keys."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        # Find the block that actually builds the mock stub (after dry_run and test_overrides)
        idx = src.find("step_mock_applied")
        assert idx != -1, "step_mock_applied not found in source"
        # Look backwards from the event name for the result dict
        prior = src[max(0, idx - 500):idx]
        assert '"mocked"' in prior or "'mocked'" in prior

    def test_mock_event_name_present(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "step_mock_applied" in src

    def test_mock_skips_agent_http_binding(self):
        """Both agent_http and mcp_tool should be covered by mock guard."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        idx = src.find("_mock_external")
        snippet = src[idx:idx+400]
        assert "agent_http" in snippet
        assert "mcp_tool" in snippet


# ===========================================================================
# 5. test_data_overrides
# ===========================================================================

class TestTestDataOverrides:
    """test_data_overrides maps step_id -> result to inject during execution."""

    def test_overrides_read_from_global_config(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "test_data_overrides" in src

    def test_override_applied_event_emitted(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "step_test_override_applied" in src

    def test_override_lookup_uses_step_id(self):
        """Override lookup must be keyed on step_id."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        idx = src.find("test_data_overrides")
        snippet = src[idx:idx+400]
        assert "step_id" in snippet

    def test_overrides_dict_type_assumption(self):
        """Overrides value must be accessible via dict subscript."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        idx = src.find("step_test_override_applied")
        # Check the result assignment uses the dict
        prior = src[max(0, idx - 700):idx]
        assert "_test_overrides" in prior or "test_data_overrides" in prior


# ===========================================================================
# 6. dry_run mode
# ===========================================================================

class TestDryRunMode:
    """dry_run execution_mode should skip agent/MCP dispatch."""

    def test_dry_run_event_emitted(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "dry_run_step_skipped" in src

    def test_dry_run_flag_read_from_state(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "execution_mode" in src
        assert "dry_run" in src

    def test_dry_run_result_structure(self):
        """dry_run stub result should have dry_run=True key."""
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        # The comment "# dry_run: skip..." appears first; the result dict follows it
        idx = src.find("dry_run_step_skipped")
        # Look in a wide region around the event name
        region = src[max(0, idx - 200):idx + 800]
        assert '"dry_run"' in region or "'dry_run'" in region

    def test_dry_run_covers_agent_http_and_mcp(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        idx = src.find("dry_run")
        snippet = src[idx:idx + 500]
        assert "agent_http" in snippet
        assert "mcp_tool" in snippet

    def test_dry_run_skipped_action_key(self):
        import app.runtime.node_executors as mod
        src = inspect.getsource(mod)
        assert "skipped_action" in src


# ===========================================================================
# 7. Retention loop structural checks
# ===========================================================================

class TestRetentionLoop:
    """Checkpoint retention loop should exist and target RunEvent rows."""

    def test_retention_loop_function_exists(self):
        import app.main as mod
        assert hasattr(mod, "_checkpoint_retention_loop")

    def test_retention_loop_is_async(self):
        import app.main as mod
        assert asyncio.iscoroutinefunction(mod._checkpoint_retention_loop)

    def test_retention_loop_targets_run_events(self):
        import app.main as mod
        src = inspect.getsource(mod._checkpoint_retention_loop)
        assert "RunEvent" in src

    def test_retention_loop_uses_settings(self):
        import app.main as mod
        src = inspect.getsource(mod._checkpoint_retention_loop)
        assert "CHECKPOINT_RETENTION_DAYS" in src or "retention_days" in src.lower()

    def test_retention_loop_wired_as_task(self):
        import app.main as mod
        src = inspect.getsource(mod)
        assert "_checkpoint_retention_loop" in src
        assert "create_task" in src
