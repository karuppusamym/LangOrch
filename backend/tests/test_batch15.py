"""
Tests for Batch 15 features:
  1. notify_on_error=True emits step_error_notification event
  2. notify_on_error=False does NOT emit any notification event
  3. notify_on_error=True fires alert webhook (fire-and-forget)
  4. notify_on_error notification survives DB emit failure (no secondary exception)
  5. notify_on_error carries error_type, error msg, and handler_action in payload
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from contextlib import asynccontextmanager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_step(*, action="navigate", output_variable=None):
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
    # Force internal executor path so resolve_executor is never called
    step.executor_binding = MagicMock()
    step.executor_binding.kind = "internal"
    return step


def _make_eh(
    *,
    action="ignore",
    error_type=None,
    fallback_node=None,
    max_retries=0,
    delay_ms=0,
    notify_on_error=False,
    recovery_steps=None,
):
    eh = MagicMock()
    eh.action = action
    eh.error_type = error_type
    eh.fallback_node = fallback_node
    eh.max_retries = max_retries
    eh.delay_ms = delay_ms
    eh.notify_on_error = notify_on_error
    eh.recovery_steps = recovery_steps or []
    return eh


def _make_node(step):
    node = MagicMock()
    node.node_id = "n1"
    node.payload = MagicMock()
    node.payload.steps = [step]
    node.payload.error_handlers = []
    return node


def _base_state(*, run_id="run-test-15"):
    return {
        "vars": {},
        "current_node_id": "n1",
        "next_node_id": None,
        "events": [],
        "error": None,
        "execution_mode": "normal",
        "run_id": run_id,
    }


def _make_db_factory(captured_events: list):
    """Return an async context-manager db_factory that captures emit_event calls."""
    mock_db = AsyncMock()

    async def fake_emit_event(db, run_id, event_type, node_id=None, step_id=None, payload=None):
        captured_events.append(
            {
                "run_id": run_id,
                "event_type": event_type,
                "node_id": node_id,
                "step_id": step_id,
                "payload": payload,
            }
        )

    @asynccontextmanager
    async def db_factory():
        yield mock_db

    return db_factory, mock_db, fake_emit_event


# ---------------------------------------------------------------------------
# 1. notify_on_error=True emits step_error_notification event
# ---------------------------------------------------------------------------


class TestNotifyOnError:
    @pytest.mark.asyncio
    async def test_notify_on_error_true_emits_event(self):
        """When notify_on_error=True, a step_error_notification event is emitted."""
        from app.runtime.node_executors import execute_sequence

        captured = []
        db_factory, _, fake_emit = _make_db_factory(captured)

        step = _make_step(output_variable="res")
        eh = _make_eh(action="ignore", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise RuntimeError("step boom")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=fake_emit),
            patch(
                "app.services.execution_service._fire_alert_webhook",
                new_callable=AsyncMock,
            ),
        ):
            await execute_sequence(node, state, db_factory=db_factory)

        # At least one step_error_notification event should have been emitted
        notif_events = [e for e in captured if e["event_type"] == "step_error_notification"]
        assert len(notif_events) == 1, f"Expected 1 notification event, got: {captured}"
        notif = notif_events[0]
        assert notif["node_id"] == "n1"
        assert notif["step_id"] == "s1"

    @pytest.mark.asyncio
    async def test_notify_on_error_false_no_event(self):
        """When notify_on_error=False (default), no notification event is emitted."""
        from app.runtime.node_executors import execute_sequence

        captured = []
        db_factory, _, fake_emit = _make_db_factory(captured)

        step = _make_step(output_variable="res")
        eh = _make_eh(action="ignore", notify_on_error=False)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise RuntimeError("failure")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=fake_emit),
        ):
            await execute_sequence(node, state, db_factory=db_factory)

        notif_events = [e for e in captured if e["event_type"] == "step_error_notification"]
        assert len(notif_events) == 0, f"Expected 0 notification events, got: {captured}"

    @pytest.mark.asyncio
    async def test_notify_on_error_payload_contains_error_info(self):
        """Emitted notification event includes error_type, error, and handler_action."""
        from app.runtime.node_executors import execute_sequence

        captured = []
        db_factory, _, fake_emit = _make_db_factory(captured)

        step = _make_step(output_variable="out")
        eh = _make_eh(action="ignore", error_type="ValueError", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise ValueError("bad input")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=fake_emit),
            patch(
                "app.services.execution_service._fire_alert_webhook",
                new_callable=AsyncMock,
            ),
        ):
            await execute_sequence(node, state, db_factory=db_factory)

        notifs = [e for e in captured if e["event_type"] == "step_error_notification"]
        assert len(notifs) == 1
        p = notifs[0]["payload"]
        assert p is not None
        assert p.get("error_type") == "ValueError"
        assert "bad input" in str(p.get("error", ""))
        assert p.get("handler_action") == "ignore"

    @pytest.mark.asyncio
    async def test_notify_on_error_fires_alert_webhook(self):
        """When notify_on_error=True, _fire_alert_webhook is called."""
        from app.runtime.node_executors import execute_sequence

        captured = []
        db_factory, _, fake_emit = _make_db_factory(captured)

        step = _make_step(output_variable="res")
        eh = _make_eh(action="ignore", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state(run_id="run-webhook-test")

        async def failing_step(action, params, vs):
            raise RuntimeError("webhook test")

        webhook_calls = []

        async def fake_webhook(run_id, exc):
            webhook_calls.append({"run_id": run_id, "exc": exc})

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=fake_emit),
            patch(
                "app.services.execution_service._fire_alert_webhook",
                side_effect=fake_webhook,
            ),
        ):
            # asyncio.ensure_future schedules the webhook — drain pending tasks
            await execute_sequence(node, state, db_factory=db_factory)
            # Allow event loop to process ensure_future tasks
            await asyncio.sleep(0.05)

        # The webhook should have been scheduled via ensure_future and run
        assert len(webhook_calls) >= 1, "_fire_alert_webhook was not called"
        assert webhook_calls[0]["run_id"] == "run-webhook-test"

    @pytest.mark.asyncio
    async def test_notify_on_error_db_failure_does_not_abort_handler(self):
        """If the DB emit for notify_on_error fails, the error handler still completes."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(output_variable="res")
        eh = _make_eh(action="ignore", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise RuntimeError("step error")

        # Only explode on the step_error_notification event; let others pass
        async def selective_exploding_emit(db, run_id, event_type, **kwargs):
            if event_type == "step_error_notification":
                raise ConnectionError("DB is down")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=selective_exploding_emit),
            patch(
                "app.services.execution_service._fire_alert_webhook",
                new_callable=AsyncMock,
            ),
        ):
            @asynccontextmanager
            async def bad_db_factory():
                yield AsyncMock()

            # Should NOT raise — the except block in notify_on_error swallows the DB error
            result = await execute_sequence(node, state, db_factory=bad_db_factory)

        # The handler still ran (ignore action suppresses error, output var nulled)
        assert result["vars"].get("res") is None
        assert result.get("error") is None

    @pytest.mark.asyncio
    async def test_notify_on_error_without_db_factory_no_crash(self):
        """notify_on_error=True with db_factory=None should not crash."""
        from app.runtime.node_executors import execute_sequence

        step = _make_step(output_variable="res")
        eh = _make_eh(action="ignore", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise RuntimeError("no db")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch(
                "app.services.execution_service._fire_alert_webhook",
                new_callable=AsyncMock,
            ),
        ):
            # db_factory=None → the DB emit block is skipped, only webhook fires
            result = await execute_sequence(node, state, db_factory=None)

        assert result["vars"].get("res") is None  # ignore handler worked

    @pytest.mark.asyncio
    async def test_notify_on_error_no_handler_match_no_event(self):
        """If the error type does not match the handler, notify_on_error is not triggered."""
        from app.runtime.node_executors import execute_sequence

        captured = []
        _, __, fake_emit = _make_db_factory(captured)

        step = _make_step(output_variable="res")
        # Handler only matches "TypeError", but we raise "ValueError"
        eh = _make_eh(action="ignore", error_type="TypeError", notify_on_error=True)
        node = _make_node(step)
        node.payload.error_handlers = [eh]

        state = _base_state()

        async def failing_step(action, params, vs):
            raise ValueError("wrong type")

        with (
            patch("app.runtime.node_executors._execute_step_action", side_effect=failing_step),
            patch("app.services.run_service.emit_event", side_effect=fake_emit),
        ):
            # db_factory=None: no DB resolve, no step_started event; handler never matches
            with pytest.raises(ValueError):
                await execute_sequence(node, state, db_factory=None)

        notifs = [e for e in captured if e["event_type"] == "step_error_notification"]
        assert len(notifs) == 0
