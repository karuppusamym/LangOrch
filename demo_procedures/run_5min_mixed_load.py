from __future__ import annotations

import argparse
import csv
import json
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://localhost:8000/api"
WORKSPACE = Path(__file__).resolve().parent.parent

DEMO_PROCEDURES: dict[str, Path] = {
    "simple-http-test": WORKSPACE / "demo_procedures" / "simple_http_test.ckp.json",
    "web-playwright-real-demo": WORKSPACE / "demo_procedures" / "web_playwright_real_demo.ckp.json",
    "hybrid-tool-workflow-dispatch-demo": WORKSPACE / "demo_procedures" / "hybrid_tool_workflow_dispatch_demo.ckp.json",
}

DEFAULT_ORDER = [
    "simple-http-test",
    "web-playwright-real-demo",
    "hybrid-tool-workflow-dispatch-demo",
]


def _get(url: str, timeout: int = 10) -> Any:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(url: str, payload: dict[str, Any], timeout: int = 15) -> Any:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ensure_backend() -> None:
    health = _get(f"{BASE_URL}/health", timeout=5)
    if health.get("status") != "ok":
        raise RuntimeError(f"Backend health not OK: {health}")


def import_or_reuse_procedure(ckp_file: Path) -> dict[str, Any]:
    ckp = json.loads(ckp_file.read_text(encoding="utf-8"))
    procedure_id = ckp["procedure_id"]
    version = ckp["version"]

    existing = _get(f"{BASE_URL}/procedures")
    for proc in existing:
        if proc.get("procedure_id") == procedure_id and proc.get("version") == version:
            return proc

    return _post(f"{BASE_URL}/procedures", {"ckp_json": ckp})


def wait_for_agents(channel: str, min_count: int, timeout_seconds: int = 30) -> int:
    """Wait until at least ``min_count`` online agents are registered for channel."""
    deadline = time.time() + timeout_seconds
    channel_norm = channel.strip().lower()
    while time.time() < deadline:
        try:
            agents = _get(f"{BASE_URL}/agents")
        except Exception:
            agents = []
        online = [
            agent for agent in agents
            if str(agent.get("channel") or "").strip().lower() == channel_norm
            and str(agent.get("status") or "").strip().lower() == "online"
        ]
        if len(online) >= min_count:
            return len(online)
        time.sleep(1)
    return 0


def build_input_vars(procedure_id: str, i: int) -> dict[str, Any]:
    if procedure_id == "simple-http-test":
        return {"post_id": (i % 100) + 1}
    if procedure_id == "web-playwright-real-demo":
        return {"target_url": "https://example.com"}
    if procedure_id == "hybrid-tool-workflow-dispatch-demo":
        return {
            "target_url": "https://example.com",
            "username": f"demo_user_{i}",
        }
    return {}


def create_run(procedure_id: str, version: str, input_vars: dict[str, Any]) -> dict[str, Any]:
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": input_vars,
    }
    return _post(f"{BASE_URL}/runs", payload)


def fetch_run_status(run_id: str) -> str:
    run = _get(f"{BASE_URL}/runs/{run_id}")
    return str(run.get("status") or "unknown")


def fetch_run_events(run_id: str) -> list[dict[str, Any]]:
    events = _get(f"{BASE_URL}/runs/{run_id}/events")
    if isinstance(events, list):
        return events
    return []


def write_csv_report(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "run_id",
        "procedure_id",
        "status",
        "pool_saturated_count",
        "analyzed_events",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="5-minute mixed LangOrch load demo")
    parser.add_argument("--duration-seconds", type=int, default=300, help="How long to submit jobs (default: 300)")
    parser.add_argument("--submit-interval-seconds", type=float, default=2.0, help="Delay between job submissions")
    parser.add_argument("--grace-seconds", type=int, default=60, help="Wait after submission window before final status summary")
    parser.add_argument("--skip-import", action="store_true", help="Do not auto-import demo procedures")
    parser.add_argument("--event-analysis-limit", type=int, default=100, help="Analyze up to N created runs for event-level stats (default: 100)")
    parser.add_argument("--csv-output", type=str, default="", help="Optional CSV report path (e.g. demo_procedures/load_report.csv)")
    parser.add_argument("--required-web-agents", type=int, default=1, help="Minimum online WEB agents required before submitting runs")
    parser.add_argument("--required-hybrid-agents", type=int, default=1, help="Minimum online HYBRID agents required before submitting runs")
    parser.add_argument("--agent-wait-timeout-seconds", type=int, default=30, help="Max time to wait for required agents")
    args = parser.parse_args()

    print("== LangOrch 5-minute mixed load demo ==")
    print("Tip: Same-pool WEB agents -> backend/demo_agents/run_5_web_agents.ps1")
    print("Tip: Split-pool WEB agents -> backend/demo_agents/run_5_web_agents_split_pools.ps1")
    ensure_backend()
    print("✓ Backend healthy")

    if args.required_web_agents > 0:
        found = wait_for_agents("web", args.required_web_agents, args.agent_wait_timeout_seconds)
        if found < args.required_web_agents:
            raise RuntimeError(
                f"Required WEB agents not ready: required={args.required_web_agents}, found={found}"
            )
        print(f"✓ WEB agents ready: found={found}")

    if args.required_hybrid_agents > 0:
        found = wait_for_agents("hybrid", args.required_hybrid_agents, args.agent_wait_timeout_seconds)
        if found < args.required_hybrid_agents:
            raise RuntimeError(
                f"Required HYBRID agents not ready: required={args.required_hybrid_agents}, found={found}"
            )
        print(f"✓ HYBRID agents ready: found={found}")

    active: list[tuple[str, str]] = []
    if args.skip_import:
        procs = _get(f"{BASE_URL}/procedures")
        lookup = {(p.get("procedure_id"), p.get("version")): p for p in procs}
        for procedure_id in DEFAULT_ORDER:
            ckp = json.loads(DEMO_PROCEDURES[procedure_id].read_text(encoding="utf-8"))
            key = (ckp["procedure_id"], ckp["version"])
            if key not in lookup:
                raise RuntimeError(f"Procedure not found and --skip-import set: {key[0]} v{key[1]}")
            active.append((key[0], key[1]))
    else:
        for procedure_id in DEFAULT_ORDER:
            proc = import_or_reuse_procedure(DEMO_PROCEDURES[procedure_id])
            active.append((proc["procedure_id"], proc["version"]))
        print("✓ Demo procedures ready:", ", ".join(p for p, _ in active))

    created: list[tuple[str, str]] = []
    failures = 0
    i = 0
    deadline = time.time() + args.duration_seconds

    print(f"✓ Submitting runs for {args.duration_seconds}s (interval={args.submit_interval_seconds}s)")
    while time.time() < deadline:
        procedure_id, version = active[i % len(active)]
        input_vars = build_input_vars(procedure_id, i)
        try:
            run = create_run(procedure_id, version, input_vars)
            run_id = run["run_id"]
            created.append((run_id, procedure_id))
            print(f"  + run={run_id} proc={procedure_id}")
        except Exception as exc:
            failures += 1
            print(f"  ! submit failed proc={procedure_id}: {exc}")
        i += 1
        time.sleep(args.submit_interval_seconds)

    print(f"✓ Submission done: created={len(created)}, submit_failures={failures}")

    if args.grace_seconds > 0:
        print(f"… waiting grace period: {args.grace_seconds}s")
        time.sleep(args.grace_seconds)

    status_counts: dict[str, int] = {}
    status_by_proc: dict[str, dict[str, int]] = {}
    for run_id, proc_name in created:
        try:
            st = fetch_run_status(run_id)
        except Exception:
            st = "unknown"
        status_counts[st] = status_counts.get(st, 0) + 1
        proc_bucket = status_by_proc.setdefault(proc_name, {})
        proc_bucket[st] = proc_bucket.get(st, 0) + 1

    analyze_count = min(len(created), max(0, args.event_analysis_limit))
    pool_saturated_total = 0
    pool_saturated_runs = 0
    pool_saturated_by_proc: dict[str, int] = {}
    pool_saturated_by_run: dict[str, int] = {}
    csv_rows: list[dict[str, Any]] = []
    if analyze_count:
        for run_id, proc_name in created[:analyze_count]:
            try:
                events = fetch_run_events(run_id)
                ps_count = sum(1 for ev in events if ev.get("event_type") == "pool_saturated")
                analyzed_events = len(events)
            except Exception:
                ps_count = 0
                analyzed_events = 0
            pool_saturated_by_run[run_id] = ps_count
            if ps_count > 0:
                pool_saturated_runs += 1
                pool_saturated_total += ps_count
                pool_saturated_by_proc[proc_name] = pool_saturated_by_proc.get(proc_name, 0) + ps_count
            csv_rows.append(
                {
                    "run_id": run_id,
                    "procedure_id": proc_name,
                    "status": fetch_run_status(run_id),
                    "pool_saturated_count": ps_count,
                    "analyzed_events": analyzed_events,
                }
            )

    if analyze_count < len(created):
        for run_id, proc_name in created[analyze_count:]:
            csv_rows.append(
                {
                    "run_id": run_id,
                    "procedure_id": proc_name,
                    "status": fetch_run_status(run_id),
                    "pool_saturated_count": "",
                    "analyzed_events": "",
                }
            )

    print("\n== Final status summary ==")
    for st in sorted(status_counts.keys()):
        print(f"  {st}: {status_counts[st]}")
    print(f"  total_runs: {len(created)}")

    print("\n== Status by procedure ==")
    for proc_name in sorted(status_by_proc.keys()):
        details = ", ".join(f"{k}={v}" for k, v in sorted(status_by_proc[proc_name].items()))
        print(f"  {proc_name}: {details}")

    print("\n== Pool saturation analysis ==")
    print(f"  analyzed_runs: {analyze_count}")
    print(f"  runs_with_pool_saturated: {pool_saturated_runs}")
    print(f"  total_pool_saturated_events: {pool_saturated_total}")
    if pool_saturated_by_proc:
        for proc_name in sorted(pool_saturated_by_proc.keys()):
            print(f"  {proc_name}: pool_saturated_events={pool_saturated_by_proc[proc_name]}")
    else:
        print("  no pool_saturated events detected")

    if args.csv_output.strip():
        report_path = Path(args.csv_output.strip())
        if not report_path.is_absolute():
            report_path = WORKSPACE / report_path
        write_csv_report(report_path, csv_rows)
        print(f"\nCSV report written: {report_path}")

    print("\nOpen UI: http://localhost:3000/runs")


if __name__ == "__main__":
    main()
