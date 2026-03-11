"""Demo: Run a case triage workflow using the bounded swarm agent.

This script demonstrates how the swarm agent integrates into LangOrch:
1. Backend orchestrator remains in control
2. Swarm agent handles bounded reasoning (classification, risk review, routing)
3. LangOrch resumes the run and routes deterministically based on swarm output

Prerequisites:
- Backend running on http://127.0.0.1:8000
- Swarm agent running on http://127.0.0.1:9006
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import requests

BASE_URL = "http://localhost:8000/api"
SWARM_AGENT_URL = "http://127.0.0.1:9006"
CKP_FILE = Path(r"c:\Users\karup\AGProjects\LangOrch\ckp_file-main\demo_case_triage_with_swarm.json")


def _get(url: str, timeout: int = 10) -> Any:
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _post(url: str, payload: dict[str, Any], timeout: int = 15) -> Any:
    r = requests.post(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def _put(url: str, payload: dict[str, Any], timeout: int = 10) -> Any:
    r = requests.put(url, json=payload, timeout=timeout)
    r.raise_for_status()
    return r.json()


def ensure_backend() -> None:
    """Verify backend is responsive."""
    try:
        health = _get(f"{BASE_URL}/health", timeout=5)
        if health.get("status") == "ok":
            return
    except Exception as e:
        raise RuntimeError(f"Backend health check failed: {e}")
    raise RuntimeError("Backend health check did not return OK")


def ensure_swarm_agent_health() -> dict[str, Any]:
    """Verify swarm agent is running and responding."""
    try:
        health = _get(f"{SWARM_AGENT_URL}/health", timeout=5)
        return health
    except Exception as e:
        raise RuntimeError(
            f"Swarm agent health check failed. "
            f"Is it running on {SWARM_AGENT_URL}? "
            f"Start it with: powershell -ExecutionPolicy Bypass -File backend/demo_agents/run_swarm_agent.ps1\n{e}"
        )


def upsert_swarm_agent() -> dict[str, Any]:
    """Register or update the swarm agent in LangOrch."""
    payload = {
        "agent_id": "swarm-demo-agent",
        "name": "Bounded Swarm Demo Agent",
        "channel": "swarm",
        "base_url": SWARM_AGENT_URL,
        "concurrency_limit": 2,
        "resource_key": "swarm_default",
        "capabilities": [
            {"name": "swarm.case_triage", "type": "workflow"},
            {"name": "swarm.document_review", "type": "workflow"},
        ]
    }

    existing_agents = _get(f"{BASE_URL}/agents")
    for agent in existing_agents:
        if agent.get("agent_id") == payload["agent_id"]:
            update_payload = {
                "status": "online",
                "base_url": payload["base_url"],
                "concurrency_limit": payload["concurrency_limit"],
                "capabilities": payload["capabilities"]
            }
            return _put(f"{BASE_URL}/agents/{payload['agent_id']}", update_payload)

    return _post(f"{BASE_URL}/agents", payload)


def import_or_reuse_procedure(ckp_file: Path) -> dict[str, Any]:
    """Import the procedure or find existing version."""
    ckp = json.loads(ckp_file.read_text(encoding="utf-8"))
    procedure_id = ckp.get("id")
    version = ckp.get("version", 1)

    existing_procedures = _get(f"{BASE_URL}/procedures")
    for proc in existing_procedures:
        if proc.get("procedure_id") == procedure_id and proc.get("version") == version:
            return proc

    return _post(f"{BASE_URL}/procedures", {"ckp_json": ckp})


def create_run(procedure_id: str, version: int, test_ticket: dict[str, Any]) -> dict[str, Any]:
    """Create a run with test case data."""
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": {
            "ticket_id": test_ticket["ticket_id"],
            "ticket": test_ticket,
        }
    }
    return _post(f"{BASE_URL}/runs", payload)


def wait_for_completion(run_id: str, timeout_seconds: int = 120) -> dict[str, Any]:
    """Poll until run reaches terminal state."""
    started = time.time()
    terminal_statuses = {"succeeded", "completed", "failed", "canceled"}
    last_status = None

    while True:
        run = _get(f"{BASE_URL}/runs/{run_id}", timeout=10)
        status = run.get("status")

        if status != last_status:
            print(f"  status={status}")
            last_status = status

        if status in terminal_statuses:
            return run

        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Run {run_id} did not complete within {timeout_seconds}s")

        time.sleep(2)


def create_test_cases() -> list[dict[str, Any]]:
    """Create a handful of test tickets to demonstrate the swarm routing."""
    return [
        {
            "ticket_id": "TICKET-001",
            "customer_id": "CUST-100",
            "body": "We received a refund notice but were never charged. The invoice shows billing_dispute.",
            "channel": "email"
        },
        {
            "ticket_id": "TICKET-002",
            "customer_id": "CUST-101",
            "body": "We have a potential security breach incident on our data transfer mechanism involving PII.",
            "channel": "support"
        },
        {
            "ticket_id": "TICKET-003",
            "customer_id": "CUST-102",
            "body": "Our MSA renewal contract needs legal review before signature.",
            "channel": "email"
        },
    ]


def main() -> None:
    print("=" * 70)
    print("LangOrch Swarm Agent Demo: Case Triage with Bounded Reasoning")
    print("=" * 70)
    print()

    print("[1/6] Checking backend health...")
    ensure_backend()
    print("✓ Backend is healthy")

    print("[2/6] Checking swarm agent health...")
    agent_health = ensure_swarm_agent_health()
    print(f"✓ Swarm agent is healthy")
    print(f"      Capabilities: {', '.join(cap['name'] for cap in agent_health.get('capabilities', []))}")

    print("[3/6] Registering swarm agent in orchestrator...")
    agent = upsert_swarm_agent()
    print(f"✓ Agent registered: {agent['agent_id']} (channel={agent.get('channel')})")

    print("[4/6] Importing CKP procedure...")
    if not CKP_FILE.exists():
        raise FileNotFoundError(f"CKP file not found: {CKP_FILE}")
    procedure = import_or_reuse_procedure(CKP_FILE)
    proc_id = procedure.get("procedure_id")
    proc_ver = procedure.get("version", 1)
    print(f"✓ Procedure ready: {proc_id} v{proc_ver}")

    print("[5/6] Creating test runs...")
    test_cases = create_test_cases()
    runs = []

    for test_case in test_cases:
        run = create_run(proc_id, proc_ver, test_case)
        run_id = run["run_id"]
        runs.append({
            "run_id": run_id,
            "ticket_id": test_case["ticket_id"],
            "body": test_case["body"]
        })
        print(f"✓ Run created: {run_id} (ticket={test_case['ticket_id']})")

    print("[6/6] Waiting for runs to complete...")
    print()

    results = []
    for run_info in runs:
        print(f"  Waiting for {run_info['run_id']}...")
        final = wait_for_completion(run_info["run_id"], timeout_seconds=120)
        results.append({
            **run_info,
            "status": final.get("status"),
            "variables": final.get("variables", {})
        })

    print()
    print("=" * 70)
    print("RESULTS")
    print("=" * 70)
    for result in results:
        print()
        print(f"Run: {result['run_id']}")
        print(f"Ticket: {result['ticket_id']}")
        print(f"Status: {result['status']}")
        swarm_result = result.get("variables", {}).get("swarm_result", {})
        if swarm_result:
            print(f"  Issue Type: {swarm_result.get('issue_type')}")
            print(f"  Urgency: {swarm_result.get('urgency')}")
            print(f"  Recommended Route: {swarm_result.get('recommended_route')}")
            print(f"  Confidence: {swarm_result.get('confidence')}")
            risk_flags = swarm_result.get("risk_flags", [])
            if risk_flags:
                print(f"  Risk Flags: {', '.join(risk_flags)}")
        else:
            print("  (No swarm result captured)")

    print()
    print("=" * 70)
    print("Demo complete!")
    print()
    print("Next steps:")
    print("1. Visit http://localhost:3000/runs to view all runs in the UI")
    print("2. Inspect the run timeline to see swarm delegation and callback events")
    print("3. Review the specialist reports in run variables")
    print()


if __name__ == "__main__":
    main()
