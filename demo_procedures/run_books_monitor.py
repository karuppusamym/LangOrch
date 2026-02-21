"""Books Price Monitor — end-to-end demo runner.

Orchestrates a full real-world scraping workflow against books.toscrape.com
using a visible Playwright browser (headless=false).

Prerequisites:
  1. Backend running:
       cd backend && .venv\\Scripts\\uvicorn app.main:app --reload --port 8000

  2. Playwright agent running in VISIBLE mode:
       backend/demo_agents/run_playwright_visible.ps1
       (sets WEB_AGENT_DRY_RUN=false, WEB_AGENT_HEADLESS=false)

  3. Playwright installed:
       pip install playwright
       playwright install chromium

Usage:
  python demo_procedures/run_books_monitor.py
  python demo_procedures/run_books_monitor.py --dry-run   (uses dry-run agent checks)
  python demo_procedures/run_books_monitor.py --page 2    (scrape page 2)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import requests

BASE_URL = "http://localhost:8000/api"
AGENT_URL = "http://127.0.0.1:9000"
PROCEDURE_FILE = Path(__file__).parent.parent / "ckp_file-main" / "books_price_monitor.ckp.json"

AGENT_CAPABILITIES = [
    "navigate",
    "click",
    "type",
    "wait_for_element",
    "extract_text",
    "extract_table_data",
    "select_all_text",
    "get_attribute",
    "screenshot",
    "close",
    "wait",
]


# ── Health checks ────────────────────────────────────────────────


def check_backend() -> None:
    try:
        r = requests.get(f"{BASE_URL}/health", timeout=5)
        r.raise_for_status()
    except Exception as exc:
        print(f"  ERROR: Cannot reach backend at {BASE_URL}")
        print(f"  Start it with: cd backend && .venv\\Scripts\\uvicorn app.main:app --reload --port 8000")
        raise SystemExit(1) from exc


def check_playwright_agent() -> dict:
    try:
        r = requests.get(f"{AGENT_URL}/health", timeout=5)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"  ERROR: Playwright agent is not reachable at {AGENT_URL}")
        print(f"  Start it with: .\\backend\\demo_agents\\run_playwright_visible.ps1")
        raise SystemExit(1) from exc


# ── Agent registration ────────────────────────────────────────────


def upsert_playwright_agent() -> dict:
    payload = {
        "agent_id": "playwright-web-agent",
        "name": "Playwright Web Agent",
        "channel": "web",
        "base_url": AGENT_URL,
        "concurrency_limit": 2,
        "resource_key": "web_playwright_default",
        "capabilities": AGENT_CAPABILITIES,
    }

    # Check if already registered
    r = requests.get(f"{BASE_URL}/agents", timeout=10)
    r.raise_for_status()
    for agent in r.json():
        if agent.get("agent_id") == payload["agent_id"]:
            # Update capabilities and mark online
            put = requests.put(
                f"{BASE_URL}/agents/{payload['agent_id']}",
                json={"status": "online", "base_url": AGENT_URL, "capabilities": AGENT_CAPABILITIES},
                timeout=10,
            )
            put.raise_for_status()
            return put.json()

    post = requests.post(f"{BASE_URL}/agents", json=payload, timeout=10)
    post.raise_for_status()
    return post.json()


# ── Procedure import ─────────────────────────────────────────────


def import_or_reuse_procedure(ckp: dict) -> dict:
    r = requests.get(f"{BASE_URL}/procedures", timeout=10)
    r.raise_for_status()
    for proc in r.json():
        if proc.get("procedure_id") == ckp["procedure_id"] and proc.get("version") == ckp["version"]:
            return proc

    create = requests.post(f"{BASE_URL}/procedures", json={"ckp_json": ckp}, timeout=10)
    create.raise_for_status()
    return create.json()


# ── Run lifecycle ────────────────────────────────────────────────


def create_run(procedure_id: str, version: str, catalogue_url: str) -> dict:
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": {
            "catalogue_url": catalogue_url,
        },
    }
    r = requests.post(f"{BASE_URL}/runs", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def wait_for_completion(run_id: str, timeout_seconds: int = 180) -> dict:
    started = time.time()
    terminal = {"succeeded", "completed", "failed", "canceled"}
    last_status = None

    while True:
        r = requests.get(f"{BASE_URL}/runs/{run_id}", timeout=10)
        r.raise_for_status()
        run = r.json()
        status = run.get("status")

        if status != last_status:
            elapsed = time.time() - started
            print(f"  [{elapsed:5.1f}s] status={status}")
            last_status = status

        if status in terminal:
            return run

        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Run {run_id} did not finish within {timeout_seconds}s")

        time.sleep(2)


# ── Results display ──────────────────────────────────────────────


def print_results(run: dict) -> None:
    status = run.get("status", "unknown")
    # output_vars contains raw captured variable objects; done.outputs template
    # vars are NOT separately resolved — access nested fields directly.
    vars_ = run.get("output_vars") or run.get("outputs") or {}

    titles_obj = vars_.get("book_titles") or {}
    prices_obj = vars_.get("book_prices") or {}
    count_obj  = vars_.get("total_count") or {}

    books_on_page       = titles_obj.get("count", "?")
    total_in_catalogue  = count_obj.get("text", "?")
    first_title         = titles_obj.get("text", "")
    first_price         = prices_obj.get("text", "")
    titles              = titles_obj.get("texts", [])
    prices              = prices_obj.get("texts", [])

    print()
    print("=" * 60)
    print(f"  BOOKS PRICE MONITOR — {status.upper()}")
    print("=" * 60)

    if status in ("succeeded", "completed"):
        print(f"  Books on this page : {books_on_page}")
        print(f"  Total in catalogue : {total_in_catalogue}")
        print(f"  First book title   : {first_title}")
        print(f"  First book price   : {first_price}")

        if titles and prices:
            print()
            print("  Books found on page:")
            print(f"  {'Title':<50}  {'Price':>10}")
            print(f"  {'-'*50}  {'-'*10}")
            for title, price in zip(titles[:20], prices[:20]):
                print(f"  {title[:49]:<50}  {price:>10}")
            if len(titles) > 20:
                print(f"  ... and {len(titles) - 20} more books")

        # Show screenshot URL from artifact event (URI normalized to /api/artifacts/...)
        try:
            evts = requests.get(f"{BASE_URL}/runs/{run['run_id']}/events", timeout=5).json()
            for ev in evts:
                if ev.get("event_type") == "artifact_created":
                    art_uri = (ev.get("payload") or {}).get("uri", "")
                    if art_uri.startswith("/api/"):
                        print(f"\n  Screenshot : http://localhost:8000{art_uri}")
        except Exception:
            pass

    else:
        error = run.get("error_message") or run.get("error") or run.get("error_detail", "")
        print(f"  Run did not succeed: {error}")

    print("=" * 60)
    print(f"  Frontend URL: http://localhost:3000/runs/{run['run_id']}")
    print("=" * 60)
    print()


# ── Entry point ──────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="Books Price Monitor Demo")
    parser.add_argument("--page", type=int, default=1, help="Catalogue page to scrape (default: 1)")
    args = parser.parse_args()

    catalogue_url = f"https://books.toscrape.com/catalogue/page-{args.page}.html"

    print()
    print("=" * 60)
    print("  BOOKS PRICE MONITOR — LangOrch Real-World Demo")
    print("=" * 60)
    print(f"  Target : {catalogue_url}")
    print(f"  Agent  : {AGENT_URL}  (visible Playwright)")
    print(f"  Backend: {BASE_URL}")
    print("=" * 60)
    print()

    print("[1/6] Checking backend health...")
    check_backend()
    print("  OK")

    print("[2/6] Checking Playwright agent...")
    agent_health = check_playwright_agent()
    mode = agent_health.get("mode", "unknown")
    print(f"  OK — mode={mode}")
    if mode == "dry_run":
        print("  WARNING: Agent is in dry-run mode — no real browser will open.")
        print("  Use run_playwright_visible.ps1 to start in real-browser mode.")

    print("[3/6] Registering agent with orchestrator...")
    agent = upsert_playwright_agent()
    print(f"  OK — {agent['agent_id']} (channel={agent['channel']})")

    print("[4/6] Importing workflow procedure...")
    ckp = json.loads(PROCEDURE_FILE.read_text(encoding="utf-8"))
    procedure = import_or_reuse_procedure(ckp)
    print(f"  OK — {procedure['procedure_id']} v{procedure['version']}")

    print("[5/6] Creating run...")
    run = create_run(procedure["procedure_id"], procedure["version"], catalogue_url)
    run_id = run["run_id"]
    print(f"  OK — run_id={run_id}")
    print()
    print("  The Playwright browser window should open shortly...")
    print("  Polling for completion (timeout: 3 min)...")
    print()

    print("[6/6] Waiting for workflow to complete...")
    final_run = wait_for_completion(run_id, timeout_seconds=180)

    print_results(final_run)

    sys.exit(0 if final_run.get("status") in ("succeeded", "completed") else 1)


if __name__ == "__main__":
    main()
