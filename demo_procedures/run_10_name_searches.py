"""Demo: 10-name web search using case queue pattern.

This demonstrates:
- Creating 10 cases with different person names as parameters
- Queue-based work distribution
- Multiple workers claiming cases in priority order
- Each case executes the same procedure with different parameters
- Results are stored back to case metadata

Run with:
    python demo_procedures/run_10_name_searches.py

Requirements:
- Backend API running on http://localhost:8000
- Web agent running (dry-run mode works) on http://localhost:9000
"""

from __future__ import annotations

import asyncio
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent / "backend"))

API_BASE = "http://localhost:8000"
WEB_AGENT_BASE = "http://localhost:9000"

# 10 famous computer scientists to research
NAMES_TO_RESEARCH = [
    "Alan Turing",
    "Grace Hopper",
    "Ada Lovelace",
    "Donald Knuth",
    "Richard Stallman",
    "Linus Torvalds",
    "Guido van Rossum",
    "Brendan Eich",
    "Tim Berners-Lee",
    "Steve Wozniak",
]


async def create_web_search_procedure(client: httpx.AsyncClient) -> str:
    """Create the CKP procedure for web searching."""
    procedure = {
        "procedure_id": f"web_search_person_{int(time.time())}",
        "version": "1.0.0",
        "trigger": {"type": "manual"},
        "variables_schema": {
            "case_id": {"type": "string", "required": True},
            "person_name": {"type": "string", "required": True},
            "search_timeout_ms": {"type": "integer", "default": 10000},
        },
        "global_config": {
            "max_retries": 2,
            "retry_delay_ms": 500,
            "resource_leasing": {
                "resource_key": "web_browser",
                "concurrency_limit": 2,  # Only 2 concurrent browser sessions
            },
        },
        "workflow_graph": {
            "start_node": "open_google",
            "nodes": {
                "open_google": {
                    "type": "sequence",
                    "agent": "web_agent",
                    "next_node": "search_name",
                    "steps": [
                        {
                            "step_id": "navigate_google",
                            "action": "navigate",
                            "url": "https://www.google.com",
                            "timeout_ms": "{{search_timeout_ms}}",
                        }
                    ],
                },
                "search_name": {
                    "type": "sequence",
                    "agent": "web_agent",
                    "next_node": "extract_results",
                    "steps": [
                        {
                            "step_id": "type_search",
                            "action": "type",
                            "selector": "textarea[name='q']",
                            "text": "{{person_name}} computer scientist",
                        },
                        {
                            "step_id": "submit_search",
                            "action": "type",
                            "selector": "textarea[name='q']",
                            "text": "{Enter}",
                        },
                    ],
                },
                "extract_results": {
                    "type": "sequence",
                    "agent": "web_agent",
                    "next_node": "store_in_case",
                    "steps": [
                        {
                            "step_id": "wait_for_results",
                            "action": "wait_for_element",
                            "selector": "div#search h3",
                            "timeout_ms": 5000,
                        },
                        {
                            "step_id": "extract_titles",
                            "action": "extract_text",
                            "selector": "div#search h3",
                            "output_variable": "search_results",
                        },
                    ],
                },
                "store_in_case": {
                    "type": "transform",
                    "next_node": "terminate",
                    "operations": [
                        {
                            "type": "set_variable",
                            "variable": "result_summary",
                            "value": "{{search_results[0] if search_results else 'No results'}}",
                        }
                    ],
                },
                "terminate": {
                    "type": "terminate",
                    "status": "completed",
                },
            },
        },
    }

    # Wrap in ProcedureCreate schema format
    payload = {"ckp_json": procedure}
    resp = await client.post(f"{API_BASE}/api/procedures", json=payload)
    if resp.status_code not in [200, 201]:
        print(f"❌ Failed to create procedure: {resp.status_code}")
        print(f"Response: {resp.text}")
        raise Exception(f"Procedure creation failed: {resp.text}")
    proc_id = resp.json()["procedure_id"]
    print(f"✓ Created procedure: {proc_id}")
    return proc_id


async def create_cases(client: httpx.AsyncClient) -> list[str]:
    """Create 10 cases, one for each name."""
    case_ids = []
    now = datetime.now(timezone.utc)

    for i, name in enumerate(NAMES_TO_RESEARCH):
        # First 3 are high priority with tight SLA
        priority = "high" if i < 3 else "normal"
        sla_hours = 1 if i < 3 else 24

        case = {
            "title": f"Research: {name}",
            "case_type": "person_research",
            "description": f"Search and extract biographical information about {name}",
            "priority": priority,
            "sla_due_at": (now + timedelta(hours=sla_hours)).isoformat(),
            "metadata": {
                "person_name": name,
                "search_timeout_ms": 10000,
                "research_category": "computer_science",
            },
        }

        resp = await client.post(f"{API_BASE}/api/cases", json=case)
        resp.raise_for_status()
        case_id = resp.json()["case_id"]
        case_ids.append(case_id)
        print(f"✓ Created case {i+1}/10: {name} ({priority}, {sla_hours}h SLA)")

    return case_ids


async def show_queue_analytics(client: httpx.AsyncClient):
    """Display queue analytics."""
    resp = await client.get(f"{API_BASE}/api/cases/queue/analytics")
    resp.raise_for_status()
    analytics = resp.json()

    print("\n" + "=" * 60)
    print("QUEUE ANALYTICS")
    print("=" * 60)
    print(f"Total active cases:     {analytics['total_active_cases']}")
    print(f"Unassigned:             {analytics['unassigned_cases']}")
    print(f"SLA breached:           {analytics['breached_cases']}")
    print(f"Breach risk (next 60m): {analytics['breach_risk_next_window_cases']}")
    print(f"Wait time p50:          {analytics['wait_p50_seconds']:.1f}s")
    print(f"Wait time p95:          {analytics['wait_p95_seconds']:.1f}s")
    print("=" * 60 + "\n")


async def process_case(
    client: httpx.AsyncClient,
    worker_name: str,
    procedure_id: str,
    dry_run: bool = True,
    skip_execution: bool = False,
):
    """Worker logic: claim next case, run procedure (if not skipped), release case."""
    # Get next unassigned high-priority case
    resp = await client.get(
        f"{API_BASE}/api/cases/queue",
        params={"only_unassigned": True, "limit": 1},
    )
    if resp.status_code != 200 or not resp.json():
        return None  # No cases available

    case = resp.json()[0]
    case_id = case["case_id"]
    person_name = case["metadata"]["person_name"]

    print(f"\n[{worker_name}] Claiming case: {person_name}")

    # Claim case
    resp = await client.post(
        f"{API_BASE}/api/cases/{case_id}/claim",
        json={"owner": worker_name, "set_in_progress": True},
    )
    resp.raise_for_status()

    try:
        if skip_execution:
            # Just simulate processing without running
            print(f"[{worker_name}] Simulating procedure for: {person_name} (web agent offline)")
            await asyncio.sleep(0.5)  # Simulate some work
            # Mark case as resolved with mock data
            await client.patch(
                f"{API_BASE}/api/cases/{case_id}",
                json={
                    "status": "resolved",
                    "metadata": {
                        **case["metadata"],
                        "search_completed": True,
                        "result": "(Demo mode - web agent offline)",
                        "completed_at": datetime.now(timezone.utc).isoformat(),
                    },
                },
            )
            print(f"[{worker_name}] ✓ Simulated completion: {person_name}")
        else:
            # Create run with case parameters
            run_payload = {
                "procedure_id": procedure_id,
                "trigger": "manual",
                "case_id": case_id,
                "initial_state": {
                    "case_id": case_id,
                    "person_name": person_name,
                    "search_timeout_ms": case["metadata"].get("search_timeout_ms", 10000),
                },
            }

            print(f"[{worker_name}] Starting procedure for: {person_name}")
            resp = await client.post(f"{API_BASE}/api/runs", json=run_payload)
            resp.raise_for_status()
            run_id = resp.json()["run_id"]

            # Poll until complete
            max_wait = 60  # seconds
            start = time.time()
            while time.time() - start < max_wait:
                resp = await client.get(f"{API_BASE}/api/runs/{run_id}")
                resp.raise_for_status()
                run = resp.json()

                if run["status"] in ["completed", "failed"]:
                    print(
                        f"[{worker_name}] ✓ Run {run['status']}: {person_name} "
                        f"(took {time.time() - start:.1f}s)"
                    )

                    # Update case with results
                    result_var = run.get("state", {}).get("result_summary", "No data")
                    await client.patch(
                        f"{API_BASE}/api/cases/{case_id}",
                        json={
                            "status": "resolved" if run["status"] == "completed" else "failed",
                            "metadata": {
                                **case["metadata"],
                                "search_completed": True,
                                "run_id": run_id,
                                "result": result_var,
                                "completed_at": datetime.now(timezone.utc).isoformat(),
                            },
                        },
                    )
                    break

                await asyncio.sleep(0.5)

    finally:
        # Always release case
        await client.post(
            f"{API_BASE}/api/cases/{case_id}/release",
            json={"owner": worker_name, "set_open": False},
        )
        print(f"[{worker_name}] Released case: {person_name}")

    return case_id


async def worker_loop(
    worker_name: str,
    procedure_id: str,
    total_cases: int,
    dry_run: bool = True,
    skip_execution: bool = False,
):
    """Worker that continuously processes cases from queue."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        processed = 0
        while processed < total_cases:
            case_id = await process_case(client, worker_name, procedure_id, dry_run, skip_execution)
            if case_id:
                processed += 1
            else:
                # No cases available, wait a bit
                await asyncio.sleep(1)

        print(f"\n[{worker_name}] Finished processing {processed} cases")


async def show_final_results(client: httpx.AsyncClient):
    """Display the final case results."""
    resp = await client.get(f"{API_BASE}/api/cases", params={"limit": 100})
    resp.raise_for_status()
    cases = resp.json()

    print("\n" + "=" * 60)
    print("FINAL RESULTS")
    print("=" * 60)

    for i, case in enumerate(sorted(cases, key=lambda c: c["created_at"]), 1):
        name = case["metadata"].get("person_name", "Unknown")
        status = case["status"]
        result = case["metadata"].get("result", "N/A")
        print(f"{i:2}. {name:20} | {status:12} | {result[:40]}")

    print("=" * 60 + "\n")


async def main():
    """Run the full demo."""
    print("\n" + "=" * 60)
    print("CASE QUEUE + WEB SEARCH DEMO")
    print("10 Names → Queue → Workers → Web Search → Results")
    print("=" * 60 + "\n")

    async with httpx.AsyncClient(timeout=30.0) as client:
        # Check if backend is running
        try:
            resp = await client.get(f"{API_BASE}/api/procedures")
            resp.raise_for_status()
        except Exception as e:
            print(f"❌ Backend not available at {API_BASE}")
            print(f"   Start with: cd backend && python -m uvicorn app.main:app")
            return 1

        # Check if web agent is running
        try:
            resp = await client.get(f"{WEB_AGENT_BASE}/", timeout=2.0)
            dry_run = "dry" in resp.text.lower() if hasattr(resp, 'text') else True
            print(f"✓ Web agent: {'DRY-RUN' if dry_run else 'LIVE BROWSER'} mode\n")
        except Exception:
            print(f"⚠ Web agent not running at {WEB_AGENT_BASE}")
            print(f"  Demo will create procedure but not execute runs (agent offline)\n")
            dry_run = True

        # Step 1: Create procedure
        print("STEP 1: Create web search procedure")
        print("-" * 60)
        procedure_id = await create_web_search_procedure(client)

        # Step 2: Create 10 cases
        print("\nSTEP 2: Create 10 cases with different names")
        print("-" * 60)
        case_ids = await create_cases(client)

        # Step 3: Show queue analytics
        print("\nSTEP 3: Queue state before processing")
        await show_queue_analytics(client)

        # Step 4: Start workers
        print("STEP 4: Start 2 workers to process queue")
        print("-" * 60)
        skip_execution = dry_run  # Skip if web agent not available
        workers = [
            worker_loop("worker_01", procedure_id, total_cases=5, dry_run=dry_run, skip_execution=skip_execution),
            worker_loop("worker_02", procedure_id, total_cases=5, dry_run=dry_run, skip_execution=skip_execution),
        ]

        await asyncio.gather(*workers)

        # Step 5: Show final results
        print("\nSTEP 5: Final results")
        await show_final_results(client)

        # Step 6: Final analytics
        print("STEP 6: Queue state after processing")
        await show_queue_analytics(client)

    print("✓ Demo complete!")
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code)
