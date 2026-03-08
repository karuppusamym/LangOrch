"""Batch 39 tests: event-bus trigger adapters and event trigger loop."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


class TestEventBusAdapters:
    def test_resolve_kafka_adapter(self):
        from app.runtime.event_bus_adapters import resolve_event_adapter, KafkaEventAdapter

        adapter = resolve_event_adapter("kafka://orders.created")
        assert isinstance(adapter, KafkaEventAdapter)

    def test_resolve_sqs_adapter(self):
        from app.runtime.event_bus_adapters import resolve_event_adapter, SqsEventAdapter

        adapter = resolve_event_adapter("sqs://orders-queue")
        assert isinstance(adapter, SqsEventAdapter)

    def test_unknown_scheme_returns_none(self):
        from app.runtime.event_bus_adapters import resolve_event_adapter

        assert resolve_event_adapter("redis://events") is None

    def test_parse_kafka_shorthand(self):
        from app.runtime.event_bus_adapters import _parse_kafka_source

        topic, bootstrap, group_id = _parse_kafka_source("orders.created")
        assert topic == "orders.created"
        assert bootstrap == "localhost:9092"
        assert group_id == "langorch-trigger"


class TestEventTriggerLoop:
    def test_event_trigger_loop_is_coroutine(self):
        from app.main import _event_trigger_loop

        assert asyncio.iscoroutinefunction(_event_trigger_loop)

    async def test_event_trigger_loop_skips_empty_registrations(self):
        from app.main import _event_trigger_loop

        @asynccontextmanager
        async def _fake_session():
            db = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = []
            db.execute = AsyncMock(return_value=result)
            yield db

        with patch("app.main.async_session", new=_fake_session), \
             patch("app.main._EVENT_TRIGGER_POLL_INTERVAL", 0), \
             patch("app.runtime.leader.leader_election", new=SimpleNamespace(is_leader=True)), \
             patch("app.runtime.event_bus_adapters.poll_events", new=AsyncMock()) as poll_mock:
            try:
                await asyncio.wait_for(_event_trigger_loop(), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        poll_mock.assert_not_called()

    async def test_event_trigger_loop_fires_and_acks(self):
        from app.main import _event_trigger_loop
        from app.runtime.event_bus_adapters import EventEnvelope

        reg = MagicMock()
        reg.procedure_id = "proc_event"
        reg.version = "1.0"
        reg.event_source = "kafka://orders.created"
        reg.dedupe_window_seconds = 0
        reg.id = 7

        @asynccontextmanager
        async def _fake_session():
            db = AsyncMock()
            result = MagicMock()
            result.scalars.return_value.all.return_value = [reg]
            db.execute = AsyncMock(return_value=result)
            db.commit = AsyncMock()
            yield db

        run = MagicMock()
        run.run_id = "run-event-1"

        with patch("app.main.async_session", new=_fake_session), \
             patch("app.main._EVENT_TRIGGER_POLL_INTERVAL", 0), \
             patch("app.runtime.leader.leader_election", new=SimpleNamespace(is_leader=True)), \
             patch("app.runtime.event_bus_adapters.poll_events", new=AsyncMock(return_value=[
                 EventEnvelope(payload={"order_id": "o-1"}, message_id="m1")
             ])), \
             patch("app.runtime.event_bus_adapters.ack_event", new=AsyncMock()) as ack_mock, \
             patch("app.services.trigger_service.fire_trigger", new=AsyncMock(return_value=run)) as fire_mock, \
             patch("app.services.execution_service.execute_run", new=AsyncMock()):
            try:
                await asyncio.wait_for(_event_trigger_loop(), timeout=0.5)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                pass

        assert fire_mock.called
        assert ack_mock.called
