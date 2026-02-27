"""Tests for the full OpenTelemetry observability backend.

Covers:
  - _resolve_endpoint() URL normalisation
  - setup_telemetry() no-op when no endpoint given
  - get_tracer() / get_meter() always return usable objects
  - CorrelationJsonFormatter does NOT inject trace/span when no active span
  - CorrelationJsonFormatter DOES inject trace/span when a real span is active
  - emit_event() does NOT add _trace_id/_span_id when no active span
  - emit_event() DOES add _trace_id/_span_id when a real span is active
"""

from __future__ import annotations

import json
import logging

import pytest


# ── _resolve_endpoint ──────────────────────────────────────────────────────

class TestResolveEndpoint:
    """_resolve_endpoint normalises base URLs to signal-specific OTLP paths."""

    def _fn(self, base, signal):
        from app.utils.tracing import _resolve_endpoint
        return _resolve_endpoint(base, signal)

    def test_bare_base_url_gets_signal_path(self):
        result = self._fn("http://localhost:4318", "traces")
        assert result == "http://localhost:4318/v1/traces"

    def test_full_traces_url_becomes_metrics(self):
        result = self._fn("http://localhost:4318/v1/traces", "metrics")
        assert result == "http://localhost:4318/v1/metrics"

    def test_full_traces_url_becomes_logs(self):
        result = self._fn("http://localhost:4318/v1/traces", "logs")
        assert result == "http://localhost:4318/v1/logs"

    def test_trailing_slash_stripped(self):
        result = self._fn("http://otel-collector:4318/", "traces")
        assert result == "http://otel-collector:4318/v1/traces"

    def test_none_returns_none(self):
        assert self._fn(None, "traces") is None

    def test_empty_string_returns_none(self):
        assert self._fn("", "traces") is None

    def test_already_correct_signal_path_unchanged(self):
        result = self._fn("http://localhost:4318/v1/metrics", "metrics")
        assert result == "http://localhost:4318/v1/metrics"


# ── setup_telemetry no-op ──────────────────────────────────────────────────

class TestSetupTelemetryNoOp:
    """setup_telemetry() is a no-op when no endpoint is provided."""

    def test_all_none_when_no_endpoint(self):
        from app.utils.tracing import setup_telemetry
        result = setup_telemetry()
        assert result["tracer_provider"] is None
        assert result["meter_provider"] is None
        assert result["logger_provider"] is None

    def test_empty_endpoint_is_no_op(self):
        from app.utils.tracing import setup_telemetry
        result = setup_telemetry(otlp_endpoint="")
        assert result["tracer_provider"] is None


# ── get_tracer / get_meter ─────────────────────────────────────────────────

class TestGetTracerGetMeter:
    """get_tracer() and get_meter() always return usable objects."""

    def test_get_tracer_returns_object(self):
        from app.utils.tracing import get_tracer
        t = get_tracer("test")
        assert t is not None

    def test_get_meter_returns_object(self):
        from app.utils.tracing import get_meter
        m = get_meter("test")
        assert m is not None

    def test_get_tracer_can_start_span(self):
        from app.utils.tracing import get_tracer
        tracer = get_tracer("test-no-op")
        # No-op span — should not raise
        with tracer.start_as_current_span("test_span") as span:
            assert span is not None


# ── CorrelationJsonFormatter trace context ─────────────────────────────────

class TestCorrelationJsonFormatterTraceContext:
    """CorrelationJsonFormatter injects trace_id/span_id when a real span is active."""

    def _format_record(self, extra_setup=None) -> dict:
        """Run a log record through CorrelationJsonFormatter and return parsed JSON."""
        from app.utils.logger import CorrelationJsonFormatter
        import io

        formatter = CorrelationJsonFormatter()
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname="", lineno=0,
            msg="hello", args=(), exc_info=None,
        )
        if extra_setup:
            extra_setup(record)
        formatted = formatter.format(record)
        return json.loads(formatted)

    def test_no_trace_context_when_no_active_span(self):
        """Without an active traced span, trace_id/span_id must NOT be present."""
        result = self._format_record()
        assert "trace_id" not in result
        assert "span_id" not in result

    def test_trace_context_injected_with_active_span(self):
        """With an active traced span, trace_id and span_id must be in the log."""
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry import trace, context
        from opentelemetry.trace import set_span_in_context

        # Use SDK TracerProvider so spans have valid context
        provider = TracerProvider()
        tracer = provider.get_tracer("test")

        captured: dict = {}

        with tracer.start_as_current_span("log_test_span"):
            captured = self._format_record()

        assert "trace_id" in captured, "trace_id missing from log when span is active"
        assert "span_id" in captured, "span_id missing from log when span is active"
        assert len(captured["trace_id"]) == 32, "trace_id must be 32-char hex"
        assert len(captured["span_id"]) == 16, "span_id must be 16-char hex"


# ── emit_event trace context ───────────────────────────────────────────────

class TestEmitEventTraceContext:
    """emit_event() injects trace context only when a valid span is active."""

    @pytest.mark.asyncio
    async def test_no_trace_context_without_active_span(self, tmp_path):
        """Standard test environment has no active span — payload stays clean."""
        import json as _json
        from unittest.mock import AsyncMock, MagicMock
        from app.services.run_service import emit_event

        db = MagicMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        event = await emit_event(db, "run-1", "test_event", payload={"key": "val"})
        db.add.assert_called_once()
        call_arg = db.add.call_args[0][0]
        payload = _json.loads(call_arg.payload_json)
        assert "_trace_id" not in payload
        assert "_span_id" not in payload

    @pytest.mark.asyncio
    async def test_trace_context_injected_with_active_span(self, tmp_path):
        """With a real SDK span active, _trace_id and _span_id appear in payload."""
        import json as _json
        from unittest.mock import AsyncMock, MagicMock
        from opentelemetry.sdk.trace import TracerProvider
        from app.services.run_service import emit_event

        provider = TracerProvider()
        tracer = provider.get_tracer("test")

        captured_event = {}

        async def _run():
            db = MagicMock()
            db.add = MagicMock()
            db.flush = AsyncMock()
            db.refresh = AsyncMock()
            ev = await emit_event(db, "run-2", "test_event", payload={"k": "v"})
            return db.add.call_args[0][0]

        with tracer.start_as_current_span("emit_test_span"):
            call_arg = await _run()

        payload = _json.loads(call_arg.payload_json)
        assert "_trace_id" in payload, "_trace_id missing when active span present"
        assert "_span_id" in payload, "_span_id missing when active span present"
        assert len(payload["_trace_id"]) == 32
        assert len(payload["_span_id"]) == 16

    @pytest.mark.asyncio
    async def test_null_payload_gets_trace_context(self):
        """When original payload is None and span is active, payload is created."""
        import json as _json
        from unittest.mock import AsyncMock, MagicMock
        from opentelemetry.sdk.trace import TracerProvider
        from app.services.run_service import emit_event

        provider = TracerProvider()
        tracer = provider.get_tracer("test")

        async def _run():
            db = MagicMock()
            db.add = MagicMock()
            db.flush = AsyncMock()
            db.refresh = AsyncMock()
            await emit_event(db, "run-3", "heartbeat", payload=None)
            return db.add.call_args[0][0]

        with tracer.start_as_current_span("null_payload_span"):
            call_arg = await _run()

        # payload_json should exist and contain trace context
        assert call_arg.payload_json is not None
        payload = _json.loads(call_arg.payload_json)
        assert "_trace_id" in payload
