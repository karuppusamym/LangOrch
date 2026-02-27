"""OpenTelemetry telemetry bootstrap — traces + metrics + logs.

Sets up all three OTEL signals from a single entry point.  All signals are
opt-in: nothing is enabled unless ``OTLP_ENDPOINT`` (or a per-signal override)
is configured.

Configuration (env vars or :class:`~app.config.Settings`):
    ``OTLP_ENDPOINT``
        Base OTLP HTTP collector endpoint, e.g. ``http://localhost:4318``.
        The ``/v1/{signal}`` path is appended automatically.
        A full signal URL (``http://localhost:4318/v1/traces``) is also
        accepted for backward compatibility — the path is normalised before
        being re-used for the other signals.
    ``OTLP_METRICS_ENDPOINT``
        Optional per-signal override for the metrics endpoint.
    ``OTLP_LOGS_ENDPOINT``
        Optional per-signal override for the logs endpoint.
    ``OTLP_EXPORT_INTERVAL_MS``
        Metrics export interval in milliseconds (default 30 000).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from opentelemetry import trace, metrics as otel_metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

logger = logging.getLogger("langorch.tracing")

# ── Module-level provider references (useful for tests / shutdown) ─────────
_tracer_provider: TracerProvider | None = None
_meter_provider: Any | None = None
_logger_provider: Any | None = None


# ── Helpers ────────────────────────────────────────────────────────────────

def _resolve_endpoint(base: str | None, signal: str) -> str | None:
    """Derive a signal-specific OTLP endpoint from a base URL.

    Normalises both bare base URLs (``http://localhost:4318``) and full
    signal URLs (``http://localhost:4318/v1/traces``) by stripping any
    existing ``/v1/<something>`` suffix then appending ``/v1/{signal}``.

    Returns ``None`` when *base* is falsy.
    """
    if not base:
        return None
    clean = re.sub(r"/v1/[^/]+$", "", base.rstrip("/"))
    return f"{clean}/v1/{signal}"


# ── Main setup ─────────────────────────────────────────────────────────────

def setup_telemetry(
    app=None,
    otlp_endpoint: str | None = None,
    otlp_metrics_endpoint: str | None = None,
    otlp_logs_endpoint: str | None = None,
    export_interval_ms: int = 30_000,
    service_name: str = "langorch-backend",
    service_version: str = "0.1.0",
    environment: str = "development",
) -> dict[str, Any]:
    """Initialise all three OTEL signals (traces, metrics, logs).

    Each signal is set up independently; a failure in one signal does not
    affect the others.  Returns a dict with keys ``tracer_provider``,
    ``meter_provider``, ``logger_provider`` — each is the configured
    provider instance or ``None`` if that signal is disabled.
    """
    global _tracer_provider, _meter_provider, _logger_provider

    result: dict[str, Any] = {
        "tracer_provider": None,
        "meter_provider": None,
        "logger_provider": None,
    }

    any_endpoint = otlp_endpoint or otlp_metrics_endpoint or otlp_logs_endpoint
    if not any_endpoint:
        logger.info("OpenTelemetry disabled — no OTLP endpoint configured.")
        return result

    resource = Resource.create({
        "service.name": service_name,
        "service.version": service_version,
        "deployment.environment": environment,
    })

    # ── Signal 1: Traces ───────────────────────────────────────────────────
    traces_ep = _resolve_endpoint(otlp_endpoint, "traces")
    if traces_ep:
        try:
            provider = TracerProvider(resource=resource)
            exporter = OTLPSpanExporter(endpoint=traces_ep)
            provider.add_span_processor(BatchSpanProcessor(exporter))
            trace.set_tracer_provider(provider)
            _tracer_provider = provider
            result["tracer_provider"] = provider
            if app:
                FastAPIInstrumentor.instrument_app(app)
            logger.info("OTEL traces  → %s", traces_ep)
        except Exception as exc:  # pragma: no cover
            logger.warning("OTEL traces setup failed: %s", exc)

    # ── Signal 2: Metrics ──────────────────────────────────────────────────
    metrics_ep = otlp_metrics_endpoint or _resolve_endpoint(otlp_endpoint, "metrics")
    if metrics_ep:
        try:
            from opentelemetry.sdk.metrics import MeterProvider
            from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
            from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                OTLPMetricExporter,
            )

            exporter = OTLPMetricExporter(endpoint=metrics_ep)
            reader = PeriodicExportingMetricReader(
                exporter, export_interval_millis=export_interval_ms
            )
            provider = MeterProvider(resource=resource, metric_readers=[reader])
            otel_metrics.set_meter_provider(provider)
            _meter_provider = provider
            result["meter_provider"] = provider
            logger.info(
                "OTEL metrics → %s  (interval %dms)", metrics_ep, export_interval_ms
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("OTEL metrics setup failed: %s", exc)

    # ── Signal 3: Logs ─────────────────────────────────────────────────────
    logs_ep = otlp_logs_endpoint or _resolve_endpoint(otlp_endpoint, "logs")
    if logs_ep:
        try:
            from opentelemetry._logs import set_logger_provider
            from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
            from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
            from opentelemetry.exporter.otlp.proto.http._log_exporter import (
                OTLPLogExporter,
            )

            log_exporter = OTLPLogExporter(endpoint=logs_ep)
            log_provider = LoggerProvider(resource=resource)
            log_provider.add_log_record_processor(
                BatchLogRecordProcessor(log_exporter)
            )
            set_logger_provider(log_provider)

            # Bridge Python's standard logging into the OTEL logs pipeline
            # so every log record is exported alongside traces.
            otel_log_handler = LoggingHandler(
                level=logging.NOTSET, logger_provider=log_provider
            )
            logging.getLogger().addHandler(otel_log_handler)

            _logger_provider = log_provider
            result["logger_provider"] = log_provider
            logger.info("OTEL logs    → %s", logs_ep)
        except Exception as exc:  # pragma: no cover
            logger.warning("OTEL logs setup failed: %s", exc)

    return result


# ── Backward-compatible shim (called by main.py) ───────────────────────────

def setup_tracing(app=None, otlp_endpoint: str | None = None) -> None:
    """Backward-compatible wrapper around :func:`setup_telemetry`.

    ``main.py`` calls ``setup_tracing(app, settings.OTLP_ENDPOINT)`` — this
    shim reads the additional signal-specific settings from
    :mod:`app.config` so the full multi-signal setup is transparently
    invoked without changing the call site in ``main.py``.
    """
    import os

    try:
        from app.config import settings
        metrics_ep = getattr(settings, "OTLP_METRICS_ENDPOINT", None)
        logs_ep = getattr(settings, "OTLP_LOGS_ENDPOINT", None)
        interval = getattr(settings, "OTLP_EXPORT_INTERVAL_MS", 30_000)
        env = os.getenv("ENVIRONMENT", "development")
    except Exception:  # pragma: no cover — import guard during early bootstrap
        metrics_ep = logs_ep = None
        interval = 30_000
        env = "development"

    setup_telemetry(
        app=app,
        otlp_endpoint=otlp_endpoint,
        otlp_metrics_endpoint=metrics_ep,
        otlp_logs_endpoint=logs_ep,
        export_interval_ms=interval,
        service_name="langorch-backend",
        service_version="0.1.0",
        environment=env,
    )


# ── Convenience accessors ──────────────────────────────────────────────────

def get_tracer(name: str):
    """Return a tracer.  Works even when no provider is configured
    (returns the global no-op tracer in that case)."""
    return trace.get_tracer(name)


def get_meter(name: str):
    """Return a meter.  Works even when no provider is configured
    (returns the global no-op meter in that case)."""
    return otel_metrics.get_meter(name)
