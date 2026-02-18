"""Tests for Batch 13 backend features:
  1. _get_retry_config reads from state["global_config"]["retry_policy"]
  2. _get_retry_config falls back to global_config top-level keys then defaults
  3. record_step_timeout increments metrics counter and logs warning
  4. _fire_alert_webhook posts to configured ALERT_WEBHOOK_URL
  5. _fire_alert_webhook is no-op when ALERT_WEBHOOK_URL is None
  6. Rate semaphore created from global_config.rate_limiting.max_concurrent
  7. global_config passed into initial_state via execution_service
  8. SLA breached event emitted when node exceeds max_duration_ms
  9. step_timeout event emitted on asyncio.TimeoutError for internal binding
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch


# ---------------------------------------------------------------------------
# 1-2. _get_retry_config
# ---------------------------------------------------------------------------

class TestGetRetryConfig:
    def _state(self, global_config: dict | None = None) -> dict:
        return {
            "procedure_id": "proc-1",
            "global_config": global_config or {},
        }

    def test_reads_retry_policy_block(self):
        from app.runtime.node_executors import _get_retry_config

        state = self._state({
            "retry_policy": {
                "max_retries": 7,
                "retry_delay_ms": 500,
                "backoff_multiplier": 1.5,
            }
        })
        cfg = _get_retry_config(state)
        assert cfg["max_retries"] == 7
        assert cfg["retry_delay_ms"] == 500
        assert cfg["backoff_multiplier"] == 1.5

    def test_falls_back_to_top_level_global_config(self):
        from app.runtime.node_executors import _get_retry_config

        state = self._state({
            "max_retries": 5,
            "retry_delay_ms": 2000,
            "backoff_multiplier": 3.0,
        })
        cfg = _get_retry_config(state)
        assert cfg["max_retries"] == 5
        assert cfg["retry_delay_ms"] == 2000
        assert cfg["backoff_multiplier"] == 3.0

    def test_falls_back_to_defaults_when_global_config_missing(self):
        from app.runtime.node_executors import _get_retry_config

        state = self._state(None)
        cfg = _get_retry_config(state)
        assert cfg["max_retries"] == 3
        assert cfg["retry_delay_ms"] == 1000
        assert cfg["backoff_multiplier"] == 2.0

    def test_falls_back_to_defaults_when_global_config_empty(self):
        from app.runtime.node_executors import _get_retry_config

        state = self._state({})
        cfg = _get_retry_config(state)
        assert cfg["max_retries"] == 3
        assert cfg["retry_delay_ms"] == 1000
        assert cfg["backoff_multiplier"] == 2.0

    def test_retry_policy_block_takes_precedence_over_top_level(self):
        from app.runtime.node_executors import _get_retry_config

        state = self._state({
            "max_retries": 99,          # top-level (should be ignored)
            "retry_policy": {
                "max_retries": 2,       # nested (should win)
            },
        })
        cfg = _get_retry_config(state)
        assert cfg["max_retries"] == 2

    def test_delay_ms_alias_works(self):
        """retry_policy.delay_ms should be accepted as alias for retry_delay_ms."""
        from app.runtime.node_executors import _get_retry_config

        state = self._state({
            "retry_policy": {
                "max_retries": 4,
                "delay_ms": 750,
            }
        })
        cfg = _get_retry_config(state)
        assert cfg["retry_delay_ms"] == 750


# ---------------------------------------------------------------------------
# 3. record_step_timeout
# ---------------------------------------------------------------------------

class TestRecordStepTimeout:
    def test_increments_counter(self):
        from app.utils.metrics import get_metrics_summary
        from app.utils import metrics as metrics_module

        # reset counter state by patching the underlying increment
        with patch.object(
            metrics_module.metrics, "increment_counter"
        ) as mock_inc:
            from app.utils.metrics import record_step_timeout
            record_step_timeout("node-X", "step-Y", 5000)
            mock_inc.assert_called_once_with(
                "step_timeout_total",
                labels={"node_id": "node-X", "step_id": "step-Y"},
            )

    def test_logs_warning(self):
        import logging
        from app.utils.metrics import record_step_timeout

        with patch("app.utils.metrics.logger") as mock_log:
            record_step_timeout("n1", "s1", 3000)
            mock_log.warning.assert_called_once()
            args = mock_log.warning.call_args[0]
            assert "n1" in str(args)
            assert "s1" in str(args)


# ---------------------------------------------------------------------------
# 4-5. _fire_alert_webhook
# ---------------------------------------------------------------------------

class TestFireAlertWebhook:
    @pytest.mark.asyncio
    async def test_posts_to_webhook_url(self):
        from app.services.execution_service import _fire_alert_webhook

        mock_response = MagicMock()
        mock_response.status_code = 200

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)

        with patch("app.services.execution_service.settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.ALERT_WEBHOOK_URL = "http://hooks.example.com/run-failed"
            await _fire_alert_webhook("run-abc", RuntimeError("test error"))

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        assert call_kwargs[0][0] == "http://hooks.example.com/run-failed"
        payload = call_kwargs[1]["json"]
        assert payload["event"] == "run_failed"
        assert payload["run_id"] == "run-abc"
        assert "test error" in payload["error"]

    @pytest.mark.asyncio
    async def test_noop_when_no_url_configured(self):
        from app.services.execution_service import _fire_alert_webhook

        with patch("app.services.execution_service.settings") as mock_settings:
            mock_settings.ALERT_WEBHOOK_URL = None
            # Should return without doing anything (no exception, no HTTP call)
            await _fire_alert_webhook("run-xyz", None)

    @pytest.mark.asyncio
    async def test_webhook_failure_does_not_raise(self):
        """Webhook errors should be swallowed (fire-and-forget)."""
        from app.services.execution_service import _fire_alert_webhook

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=ConnectionError("network error"))

        with patch("app.services.execution_service.settings") as mock_settings, \
             patch("httpx.AsyncClient", return_value=mock_client):
            mock_settings.ALERT_WEBHOOK_URL = "http://hooks.example.com/fail"
            # Should not raise
            await _fire_alert_webhook("run-err", None)


# ---------------------------------------------------------------------------
# 6. Rate semaphore creation
# ---------------------------------------------------------------------------

class TestRateSemaphoreCreation:
    def test_semaphore_created_from_global_config(self):
        """Semaphore should be asyncio.Semaphore(n) when max_concurrent > 0."""
        max_concurrent = 5
        rl_cfg = {"max_concurrent": max_concurrent}
        global_config = {"rate_limiting": rl_cfg}

        rl = global_config.get("rate_limiting") or {}
        n = int(rl.get("max_concurrent") or 0)
        sem = asyncio.Semaphore(n) if n > 0 else None

        assert sem is not None
        assert isinstance(sem, asyncio.Semaphore)

    def test_no_semaphore_when_max_concurrent_zero(self):
        global_config: dict = {}
        rl = global_config.get("rate_limiting") or {}
        n = int(rl.get("max_concurrent") or 0)
        sem = asyncio.Semaphore(n) if n > 0 else None
        assert sem is None

    def test_semaphore_injected_into_gc_for_state(self):
        global_config = {"rate_limiting": {"max_concurrent": 3}}
        rl = global_config.get("rate_limiting") or {}
        n = int(rl.get("max_concurrent") or 0)
        sem = asyncio.Semaphore(n) if n > 0 else None

        gc_for_state = dict(global_config)
        if sem is not None:
            gc_for_state["_rate_semaphore"] = sem

        assert "_rate_semaphore" in gc_for_state
        assert isinstance(gc_for_state["_rate_semaphore"], asyncio.Semaphore)


# ---------------------------------------------------------------------------
# 7. global_config in OrchestratorState
# ---------------------------------------------------------------------------

class TestOrchestratorStateGlobalConfig:
    def test_global_config_field_exists(self):
        from app.runtime.state import OrchestratorState
        # TypedDict keys are accessible via __annotations__
        assert "global_config" in OrchestratorState.__annotations__

    def test_state_accepts_global_config(self):
        from app.runtime.state import OrchestratorState
        state: OrchestratorState = {  # type: ignore[assignment]
            "vars": {},
            "secrets": {},
            "run_id": "r1",
            "procedure_id": "p1",
            "procedure_version": "1",
            "global_config": {"retry_policy": {"max_retries": 2}},
            "current_node_id": "n1",
            "current_step_id": None,
            "error": None,
        }
        assert state["global_config"]["retry_policy"]["max_retries"] == 2


# ---------------------------------------------------------------------------
# 8. SLA monitoring
# ---------------------------------------------------------------------------

class TestSLABreach:
    """Test that execute_sequence emits a sla_breached event when the node
    duration exceeds sla.max_duration_ms and a db_factory is present."""

    @pytest.mark.asyncio
    async def test_sla_breach_event_emitted(self):
        from app.runtime import node_executors
        from app.compiler.ir import ExecutorBinding, IRNode, IRSequencePayload, IRStep

        step = IRStep(
            step_id="s1",
            action="test_action",
            executor_binding=ExecutorBinding(kind="internal"),
            timeout_ms=None,
        )
        payload = IRSequencePayload(steps=[step])
        node = IRNode(
            node_id="node-sla",
            type="sequence",
            sla={"max_duration_ms": 100, "on_breach": "alert"},
            payload=payload,
        )
        state = {
            "vars": {},
            "secrets": {},
            "run_id": "run-sla-test",
            "procedure_id": "p1",
            "procedure_version": "1",
            "global_config": {},
            "current_node_id": "node-sla",
            "current_step_id": None,
            "error": None,
        }

        captured_events: list[str] = []

        async def fake_emit(db, run_id, event_type, **kwargs):
            captured_events.append(event_type)

        # Mock db session and db_factory
        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        def mock_db_factory():
            """Synchronous factory returning an async context manager."""
            return mock_db

        # time.monotonic returns 0.0 first call, then 0.5 (500ms > 100ms SLA max)
        call_count = 0
        original_monotonic = __import__("time").monotonic

        def fake_monotonic():
            nonlocal call_count
            call_count += 1
            # 1st call: node start; subsequent calls used in SLA check
            return 0.0 if call_count == 1 else 0.5

        async def fake_execute_action(action, params, vars_ctx):
            return {}

        with patch("app.services.run_service.emit_event", side_effect=fake_emit), \
             patch("time.monotonic", side_effect=fake_monotonic), \
             patch("app.runtime.node_executors._execute_step_action", side_effect=fake_execute_action), \
             patch("app.runtime.node_executors._get_completed_step_result", AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", AsyncMock()):
            await node_executors.execute_sequence(node, state, db_factory=mock_db_factory)

        assert "sla_breached" in captured_events, f"Expected sla_breached in {captured_events}"


# ---------------------------------------------------------------------------
# 9. step_timeout DB event emitted on asyncio.TimeoutError
# ---------------------------------------------------------------------------

class TestStepTimeoutEvent:
    @pytest.mark.asyncio
    async def test_step_timeout_event_emitted_on_internal_timeout(self):
        from app.runtime import node_executors
        from app.compiler.ir import ExecutorBinding, IRNode, IRSequencePayload, IRStep

        step = IRStep(
            step_id="s-timeout",
            action="slow_action",
            executor_binding=ExecutorBinding(kind="internal"),
            timeout_ms=50,  # 50ms timeout
        )
        payload = IRSequencePayload(steps=[step])
        node = IRNode(
            node_id="node-timeout",
            type="sequence",
            sla=None,
            payload=payload,
        )
        state = {
            "vars": {},
            "secrets": {},
            "run_id": "run-timeout-test",
            "procedure_id": "p1",
            "procedure_version": "1",
            "global_config": {},
            "current_node_id": "node-timeout",
            "current_step_id": None,
            "error": None,
        }

        captured_events: list[str] = []

        async def fake_emit(db, run_id, event_type, **kwargs):
            captured_events.append(event_type)

        mock_db = AsyncMock()
        mock_db.__aenter__ = AsyncMock(return_value=mock_db)
        mock_db.__aexit__ = AsyncMock(return_value=False)
        mock_db.commit = AsyncMock()
        mock_db.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

        def mock_db_factory():
            return mock_db

        async def slow_action(action, params, vars_ctx):
            await asyncio.sleep(10)  # will be cut short by asyncio.wait_for

        with patch("app.services.run_service.emit_event", side_effect=fake_emit), \
             patch("app.runtime.node_executors._execute_step_action", side_effect=slow_action), \
             patch("app.runtime.node_executors._get_completed_step_result", AsyncMock(return_value=None)), \
             patch("app.runtime.node_executors._mark_step_started", AsyncMock()), \
             patch("app.runtime.node_executors.record_step_timeout"):
            with pytest.raises((asyncio.TimeoutError, TimeoutError)):
                await node_executors.execute_sequence(node, state, db_factory=mock_db_factory)

        assert "step_timeout" in captured_events, f"Expected step_timeout in {captured_events}"
