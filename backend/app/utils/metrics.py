"""
Basic in-memory metrics counters for observability.

Provides simple counters for key operational metrics:
- run_duration_seconds: Histogram of run execution times
- run_failures_total: Counter of failed runs
- retry_attempts_total: Counter of retry attempts
- step_execution_total: Counter of step executions by status
"""
import re as _re
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
        """Get histogram statistics (count, sum, min, max, avg, p95)."""
        key = self._build_key(name, labels)
        values = self.histograms.get(key, [])
        
        if not values:
            return {"count": 0, "sum": 0, "min": 0, "max": 0, "avg": 0, "p95": 0}

        sorted_vals = sorted(values)
        n = len(sorted_vals)
        p95_idx = max(0, int(n * 0.95) - 1)
        return {
            "count": n,
            "sum": sum(sorted_vals),
            "min": sorted_vals[0],
            "max": sorted_vals[-1],
            "avg": sum(sorted_vals) / n,
            "p95": sorted_vals[p95_idx],
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


def _parse_metric_key(key: str) -> tuple[str, str]:
    """Split an internal metric key into (base_name, prometheus_label_string).

    Internal keys are produced by ``MetricsCollector._build_key`` in the form
    ``name`` or ``name{k1=v1,k2=v2}`` (values are unquoted).

    Returns a 2-tuple:
      base_name  — the metric name without label block, e.g. ``step_execution_total``
      label_str  — Prometheus label block with quoted values, e.g.  ``{node_id="foo",status="completed"}``
                   Empty string when there are no labels.
    """
    m = _re.match(r'^([^{]+)(?:\{(.+)\})?$', key)
    if not m:
        return key, ""
    base_name = m.group(1)
    raw_labels = m.group(2) or ""
    if not raw_labels:
        return base_name, ""
    # Rebuild with quoted values: k=v → k="v"
    label_parts: list[str] = []
    for pair in raw_labels.split(","):
        if "=" in pair:
            k, v = pair.split("=", 1)
            label_parts.append(f'{k.strip()}="{v.strip()}"')
    label_str = "{" + ",".join(label_parts) + "}" if label_parts else ""
    return base_name, label_str


def _append_quantile_label(label_str: str, quantile: str) -> str:
    """Merge a quantile key-value into an existing Prometheus label block."""
    q_pair = f'quantile="{quantile}"'
    if label_str:
        # Insert before the closing brace
        return label_str[:-1] + "," + q_pair + "}"
    return "{" + q_pair + "}"


def to_prometheus_text() -> str:
    """Render all in-memory metrics as Prometheus text exposition format.

    Produces valid Prometheus text format:
    - Each metric *family* has exactly one ``# TYPE`` comment line.
    - Label sets use the standard ``{key="value",...}`` syntax.
    - Counters with different label combinations are grouped under the same
      family name rather than being emitted as separate metric names.

    This is the canonical serialisation used by both the scrape endpoint
    (``GET /api/metrics``) and the Pushgateway push task.
    """
    summary = get_metrics_summary()
    lines: list[str] = []

    # ── Counters ───────────────────────────────────────────────────────────
    # Group by Prometheus family name so each family has exactly one # TYPE.
    counter_families: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for key, val in summary.get("counters", {}).items():
        base_name, label_str = _parse_metric_key(key)
        prom_name = "langorch_" + base_name
        counter_families[prom_name].append((label_str, val))
    for prom_name, entries in counter_families.items():
        lines.append(f"# TYPE {prom_name} counter")
        for label_str, val in entries:
            lines.append(f"{prom_name}{label_str} {val}")

    # ── Histograms (rendered as Prometheus summaries) ──────────────────────
    histogram_families: dict[str, list[tuple[str, str, dict]]] = defaultdict(list)
    for key, stats in summary.get("histograms", {}).items():
        base_name, label_str = _parse_metric_key(key)
        prom_name = "langorch_" + base_name
        histogram_families[prom_name].append((label_str, key, stats))
    for prom_name, entries in histogram_families.items():
        lines.append(f"# TYPE {prom_name} summary")
        for label_str, raw_key, stats in entries:
            if not isinstance(stats, dict):
                continue
            if stats.get("count") is not None:
                lines.append(f"{prom_name}_count{label_str} {stats['count']}")
            if stats.get("sum") is not None:
                lines.append(f"{prom_name}_sum{label_str} {stats['sum']:.6f}")
            # Emit arithmetic mean as a plain gauge (not a quantile label)
            if stats.get("avg") is not None:
                lines.append(f"{prom_name}_avg{label_str} {stats['avg']:.6f}")
            # Emit p50 quantile recomputed from raw stored values
            if stats.get("count", 0) > 0:
                raw_vals = metrics.histograms.get(raw_key, [])
                if raw_vals:
                    sv = sorted(raw_vals)
                    p50_idx = max(0, int(len(sv) * 0.50) - 1)
                    q_label = _append_quantile_label(label_str, "0.5")
                    lines.append(f"{prom_name}{q_label} {sv[p50_idx]:.6f}")
            if stats.get("p95") is not None:
                q_label = _append_quantile_label(label_str, "0.95")
                lines.append(f"{prom_name}{q_label} {stats['p95']:.6f}")
            if stats.get("max") is not None:
                q_label = _append_quantile_label(label_str, "1.0")
                lines.append(f"{prom_name}{q_label} {stats['max']:.6f}")
    return "\n".join(lines) + "\n"

