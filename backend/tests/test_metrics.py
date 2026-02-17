"""Tests for metrics utility."""

from __future__ import annotations

import pytest

from app.utils.metrics import (
    MetricsCollector,
    metrics,
    record_run_started,
    record_run_completed,
    record_retry_attempt,
    record_step_execution,
    get_metrics_summary,
)


class TestMetricsCollector:
    """Test the MetricsCollector class directly."""

    def test_increment_counter(self):
        mc = MetricsCollector()
        mc.increment_counter("test_counter")
        assert mc.get_counter("test_counter") == 1
        mc.increment_counter("test_counter")
        assert mc.get_counter("test_counter") == 2

    def test_increment_counter_with_value(self):
        mc = MetricsCollector()
        mc.increment_counter("test", value=5)
        assert mc.get_counter("test") == 5

    def test_counter_with_labels(self):
        mc = MetricsCollector()
        mc.increment_counter("runs", labels={"status": "success"})
        mc.increment_counter("runs", labels={"status": "failed"})
        mc.increment_counter("runs", labels={"status": "success"})
        assert mc.get_counter("runs", labels={"status": "success"}) == 2
        assert mc.get_counter("runs", labels={"status": "failed"}) == 1

    def test_nonexistent_counter_zero(self):
        mc = MetricsCollector()
        assert mc.get_counter("nonexistent") == 0

    def test_observe_histogram(self):
        mc = MetricsCollector()
        mc.observe_histogram("duration", 1.5)
        mc.observe_histogram("duration", 2.5)
        mc.observe_histogram("duration", 3.0)
        stats = mc.get_histogram_stats("duration")
        assert stats["count"] == 3
        assert stats["sum"] == 7.0
        assert stats["min"] == 1.5
        assert stats["max"] == 3.0
        assert abs(stats["avg"] - 7.0 / 3) < 0.001

    def test_empty_histogram(self):
        mc = MetricsCollector()
        stats = mc.get_histogram_stats("nonexistent")
        assert stats["count"] == 0
        assert stats["sum"] == 0

    def test_histogram_with_labels(self):
        mc = MetricsCollector()
        mc.observe_histogram("dur", 1.0, labels={"status": "ok"})
        mc.observe_histogram("dur", 2.0, labels={"status": "err"})
        ok_stats = mc.get_histogram_stats("dur", labels={"status": "ok"})
        err_stats = mc.get_histogram_stats("dur", labels={"status": "err"})
        assert ok_stats["count"] == 1
        assert err_stats["count"] == 1

    def test_reset(self):
        mc = MetricsCollector()
        mc.increment_counter("runs")
        mc.observe_histogram("dur", 1.0)
        mc.reset()
        assert mc.get_counter("runs") == 0
        assert mc.get_histogram_stats("dur")["count"] == 0

    def test_get_all_metrics(self):
        mc = MetricsCollector()
        mc.increment_counter("total")
        mc.observe_histogram("time", 1.0)
        result = mc.get_all_metrics()
        assert "counters" in result
        assert "histograms" in result
        assert "total" in result["counters"]

    def test_build_key_no_labels(self):
        key = MetricsCollector._build_key("name", None)
        assert key == "name"

    def test_build_key_with_labels(self):
        key = MetricsCollector._build_key("name", {"a": "1", "b": "2"})
        assert key == "name{a=1,b=2}"


class TestGlobalMetricsFunctions:
    """Test the module-level convenience functions."""

    def setup_method(self):
        """Reset global metrics before each test."""
        metrics.reset()

    def test_record_run_started(self):
        record_run_started()
        record_run_started()
        assert metrics.get_counter("run_started_total") == 2

    def test_record_run_completed_success(self):
        record_run_completed(1.5, "success")
        assert metrics.get_counter("run_completed_total", labels={"status": "success"}) == 1
        stats = metrics.get_histogram_stats("run_duration_seconds", labels={"status": "success"})
        assert stats["count"] == 1
        assert stats["sum"] == 1.5

    def test_record_run_completed_failed(self):
        record_run_completed(2.0, "failed")
        assert metrics.get_counter("run_completed_total", labels={"status": "failed"}) == 1
        assert metrics.get_counter("run_failures_total") == 1

    def test_record_retry_attempt(self):
        record_retry_attempt("node1", "step1")
        record_retry_attempt("node1", "step1")
        assert metrics.get_counter("retry_attempts_total", labels={"node_id": "node1", "step_id": "step1"}) == 2

    def test_record_step_execution(self):
        record_step_execution("node1", "completed")
        record_step_execution("node1", "failed")
        assert metrics.get_counter("step_execution_total", labels={"node_id": "node1", "status": "completed"}) == 1
        assert metrics.get_counter("step_execution_total", labels={"node_id": "node1", "status": "failed"}) == 1

    def test_get_metrics_summary(self):
        record_run_started()
        record_run_completed(1.0, "success")
        summary = get_metrics_summary()
        assert "counters" in summary
        assert "histograms" in summary
