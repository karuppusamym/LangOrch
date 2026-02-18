"""
Basic in-memory metrics counters for observability.

Provides simple counters for key operational metrics:
- run_duration_seconds: Histogram of run execution times
- run_failures_total: Counter of failed runs
- retry_attempts_total: Counter of retry attempts
- step_execution_total: Counter of step executions by status
"""
from collections import defaultdict
from datetime import datetime
from typing import Any
import logging

logger = logging.getLogger("langorch.metrics")


class MetricsCollector:
    """Simple in-memory metrics collector."""
    
    def __init__(self):
        self.counters: dict[str, int] = defaultdict(int)
        self.histograms: dict[str, list[float]] = defaultdict(list)
        
    def increment_counter(self, name: str, value: int = 1, labels: dict[str, str] | None = None):
        """Increment a counter metric."""
        key = self._build_key(name, labels)
        self.counters[key] += value
        
    def observe_histogram(self, name: str, value: float, labels: dict[str, str] | None = None):
        """Record a histogram observation."""
        key = self._build_key(name, labels)
        self.histograms[key].append(value)
        
    def get_counter(self, name: str, labels: dict[str, str] | None = None) -> int:
        """Get current counter value."""
        key = self._build_key(name, labels)
        return self.counters.get(key, 0)
    
    def get_histogram_stats(self, name: str, labels: dict[str, str] | None = None) -> dict[str, Any]:
        """Get histogram statistics (count, sum, min, max, avg)."""
        key = self._build_key(name, labels)
        values = self.histograms.get(key, [])
        
        if not values:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "avg": 0}
        
        return {
            "count": len(values),
            "sum": sum(values),
            "min": min(values),
            "max": max(values),
            "avg": sum(values) / len(values),
        }
    
    def get_all_metrics(self) -> dict[str, Any]:
        """Get all metrics as a dictionary."""
        metrics = {
            "counters": dict(self.counters),
            "histograms": {k: self.get_histogram_stats(k) for k in self.histograms.keys()}
        }
        return metrics
    
    def reset(self):
        """Reset all metrics."""
        self.counters.clear()
        self.histograms.clear()
    
    @staticmethod
    def _build_key(name: str, labels: dict[str, str] | None) -> str:
        """Build metric key from name and labels."""
        if not labels:
            return name
        label_str = ",".join(f"{k}={v}" for k, v in sorted(labels.items()))
        return f"{name}{{{label_str}}}"


# Global metrics collector instance
metrics = MetricsCollector()


def record_run_started():
    """Record a run start event."""
    metrics.increment_counter("run_started_total")


def record_run_completed(duration_seconds: float, status: str):
    """
    Record a run completion event.
    
    Args:
        duration_seconds: Run execution time in seconds
        status: Run status (completed, failed, cancelled)
    """
    metrics.increment_counter("run_completed_total", labels={"status": status})
    metrics.observe_histogram("run_duration_seconds", duration_seconds, labels={"status": status})
    
    if status == "failed":
        metrics.increment_counter("run_failures_total")


def record_retry_attempt(node_id: str, step_id: str):
    """Record a step retry attempt."""
    metrics.increment_counter("retry_attempts_total", labels={"node_id": node_id, "step_id": step_id})


def record_step_execution(node_id: str, status: str):
    """
    Record a step execution event.
    
    Args:
        node_id: Node identifier
        status: Execution status (completed, failed, cached)
    """
    metrics.increment_counter("step_execution_total", labels={"node_id": node_id, "status": status})


def record_step_timeout(node_id: str, step_id: str, timeout_ms: int):
    """Record a step timeout event."""
    metrics.increment_counter("step_timeout_total", labels={"node_id": node_id, "step_id": step_id})
    logger.warning("Step timeout: node=%s step=%s timeout_ms=%d", node_id, step_id, timeout_ms)


def record_custom_metric(name: str, value: int = 1, labels: dict[str, str] | None = None):
    """Increment a custom metric counter defined in node telemetry.custom_metrics."""
    metrics.increment_counter(name, value=value, labels=labels)


def get_metrics_summary() -> dict:
    """Get a summary of all metrics."""
    return metrics.get_all_metrics()
