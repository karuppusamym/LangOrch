"""
findeREC Group Enrollment Demo
===============================
Full browser automation through the findeREC.com organization enrollment flow:
  1. Homepage -> click Join Now
  2. Pricing page -> scroll to Family & Friends Group -> click Join Now
  3. Group Info form -> state, city, org name, checkboxes, Continue
  4. Admin User form -> first/last name, email, phone, password, Save & Continue
  5. General Org form -> org name, category, address, state, city, zip, phone, Save & Continue
  6. Wait 10s then click Continue to Payment

Prerequisites
-------------
* LangOrch backend  -> http://localhost:8000
* Playwright agent  -> http://127.0.0.1:9000  (run with WEB_AGENT_HEADLESS=false for visible browser)

Run
---
    $env:WEB_AGENT_HEADLESS = "false"
    python C:\\Users\\karup\\AGProjects\\LangOrch\\demo_procedures\\run_finderec_enrollment_demo.py
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import requests


BASE_URL  = "http://localhost:8000/api"
AGENT_URL = "http://127.0.0.1:9000"
CKP_FILE  = Path(__file__).parent / "finderec_group_enrollment_demo.ckp.json"


# helpers

def ensure_backend() -> None:
    r = requests.get(f"{BASE_URL}/health", timeout=5)
    r.raise_for_status()


def ensure_web_agent() -> dict:
    r = requests.get(f"{AGENT_URL}/health", timeout=5)
    r.raise_for_status()
    return r.json()


def upsert_web_agent() -> dict:
    payload = {
        "agent_id": "playwright-web-agent",
        "name": "Playwright Web Agent",
        "channel": "web",
        "base_url": AGENT_URL,
        "concurrency_limit": 2,
        "resource_key": "web_playwright_default",
        "capabilities": [
            # Core navigation
            {"name": "navigate",              "type": "tool"},
            {"name": "reload_page",           "type": "tool"},
            {"name": "go_back",               "type": "tool"},
            {"name": "go_forward",            "type": "tool"},
            {"name": "get_current_url",       "type": "tool"},
            {"name": "get_page_title",        "type": "tool"},
            # Element interaction
            {"name": "click",                 "type": "tool"},
            {"name": "double_click",          "type": "tool"},
            {"name": "right_click",           "type": "tool"},
            {"name": "hover",                 "type": "tool"},
            {"name": "type",                  "type": "tool"},
            {"name": "clear_field",           "type": "tool"},
            {"name": "select_option",         "type": "tool"},
            {"name": "check",                 "type": "tool"},
            {"name": "uncheck",               "type": "tool"},
            {"name": "upload_file",           "type": "tool"},
            {"name": "drag_and_drop",         "type": "tool"},
            {"name": "press_key",             "type": "tool"},
            {"name": "focus",                 "type": "tool"},
            {"name": "blur",                  "type": "tool"},
            {"name": "scroll",                "type": "tool"},
            {"name": "scroll_into_view",      "type": "tool"},
            {"name": "get_attribute",         "type": "tool"},
            {"name": "extract_text",          "type": "tool"},
            {"name": "extract_table_data",    "type": "tool"},
            {"name": "select_all_text",       "type": "tool"},
            # Dynamic waits
            {"name": "wait_for_element",      "type": "tool"},
            {"name": "wait_for_navigation",   "type": "tool"},
            {"name": "wait_for_load_state",   "type": "tool"},
            {"name": "wait_for_network_idle", "type": "tool"},
            {"name": "wait_for_url",          "type": "tool"},
            {"name": "wait_for_function",     "type": "tool"},
            # iFrame support
            {"name": "switch_frame",          "type": "tool"},
            {"name": "switch_main_frame",     "type": "tool"},
            # Multi-tab
            {"name": "new_tab",               "type": "tool"},
            {"name": "switch_tab",            "type": "tool"},
            {"name": "close_tab",             "type": "tool"},
            {"name": "get_tabs",              "type": "tool"},
            # Cookies / storage
            {"name": "get_cookies",           "type": "tool"},
            {"name": "set_cookies",           "type": "tool"},
            {"name": "clear_cookies",         "type": "tool"},
            {"name": "get_local_storage",     "type": "tool"},
            {"name": "set_local_storage",     "type": "tool"},
            # JS / CDP
            {"name": "evaluate_js",           "type": "tool"},
            {"name": "cdp_send",              "type": "tool"},
            {"name": "set_viewport",          "type": "tool"},
            {"name": "set_geolocation",       "type": "tool"},
            {"name": "emulate_device",        "type": "tool"},
            {"name": "intercept_requests",    "type": "tool"},
            {"name": "set_extra_headers",     "type": "tool"},
            # Screenshot / session
            {"name": "screenshot",            "type": "tool"},
            {"name": "close",                 "type": "tool"},
            # DOM introspection + AI locate
            {"name": "get_dom",                    "type": "tool"},
            {"name": "query_dom",                  "type": "tool"},
            {"name": "get_accessibility_snapshot", "type": "tool"},
            {"name": "ai_locate",                  "type": "tool"},
        ],
    }

    agents = requests.get(f"{BASE_URL}/agents", timeout=10)
    agents.raise_for_status()
    for agent in agents.json():
        if agent.get("agent_id") == payload["agent_id"]:
            up = requests.put(
                f"{BASE_URL}/agents/{payload['agent_id']}",
                json={
                    "status": "online",
                    "base_url": AGENT_URL,
                    "concurrency_limit": payload["concurrency_limit"],
                    "capabilities": payload["capabilities"],
                },
                timeout=10,
            )
            up.raise_for_status()
            return up.json()

    cr = requests.post(f"{BASE_URL}/agents", json=payload, timeout=10)
    cr.raise_for_status()
    return cr.json()


def import_or_reuse_procedure(ckp: dict) -> dict:
    """Import the procedure if it doesn't exist; force-update via PUT if it does.

    Using PUT on every run ensures that any local CKP edits are always reflected
    in the DB even when the version number hasn't changed.
    """
    procs = requests.get(f"{BASE_URL}/procedures", timeout=10)
    procs.raise_for_status()
    exists = any(
        p.get("procedure_id") == ckp["procedure_id"] and p.get("version") == ckp["version"]
        for p in procs.json()
    )
    if exists:
        # Force-update so any CKP edits land in the DB immediately.
        up = requests.put(
            f"{BASE_URL}/procedures/{ckp['procedure_id']}/{ckp['version']}",
            json={"ckp_json": ckp},
            timeout=10,
        )
        up.raise_for_status()
        return up.json()
    new = requests.post(f"{BASE_URL}/procedures", json={"ckp_json": ckp}, timeout=10)
    new.raise_for_status()
    return new.json()


def start_run(procedure_id: str, version: str) -> dict:
    run_suffix = str(int(time.time()))[-6:]
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": {
            # Group-info form
            "group_info_state":        "south carolina",
            "group_info_state_option": "SOUTH CAROLINA",
            "group_info_city":         "charleston",
            "group_info_city_option":  "CHARLESTON",
            "group_info_org_name":     "Harborview Community Network",
            # Admin user form
            "admin_first_name":        "Ariana",
            "admin_last_name":         "Coleman",
            "admin_email":             f"harborview.ops.{run_suffix}@example.com",
            "admin_phone":             "8434102786",
            "admin_password":          "#Harbor2026#",
            # General org form
            "general_org_name":        "Harborview Community Network",
            "general_address_line1":   "88 Cooper River Ct",
            "general_zip":             "29403",
            "general_phone":           "8434102786",
            "general_state_option":    "South Carolina",
            "general_city_option":     "Charleston",
            # Artifacts
            "artifacts_base_dir":      "c:/Users/karup/AGProjects/LangOrch/artifacts",
            # NOTE: run_id is system_generated - injected by the runtime, not supplied here
        },
    }
    r = requests.post(f"{BASE_URL}/runs", json=payload, timeout=10)
    r.raise_for_status()
    return r.json()


def poll_until_done(run_id: str, timeout_s: int = 300) -> dict:
    terminal  = {"succeeded", "completed", "failed", "canceled"}
    deadline  = time.time() + timeout_s
    last_status = None

    while True:
        r = requests.get(f"{BASE_URL}/runs/{run_id}", timeout=10)
        r.raise_for_status()
        run    = r.json()
        status = run.get("status")

        if status != last_status:
            print(f"  -> {status}")
            last_status = status

        if status in terminal:
            return run

        if time.time() > deadline:
            raise TimeoutError(f"Run {run_id} timed out after {timeout_s}s")

        time.sleep(2)


# main

STEPS = [
    ("1", "finderec.com homepage",              "open hamburger menu (top-right) -> click Join Now"),
    ("2", "finderec.com/pricing",               "scroll to Family & Friends -> click Join Now"),
    ("3", "finderec.com/group/erec-group-info", "fill state, city, org name, checkboxes -> Continue"),
    ("4", "finderec.com/group/group-admin",     "fill admin user info -> Save & Continue"),
    ("5", "finderec.com/group/erec-general",    "fill org details -> Save & Continue"),
    ("6", "payment page",                       "wait 10 s -> Continue to Payment"),
]

SCREENSHOTS = [
    "finderec_01_homepage.png",
    "finderec_02_pricing.png",
    "finderec_03_group_info.png",
    "finderec_04_admin_form.png",
    "finderec_05_general_form.png",
    "finderec_06_before_payment.png",
]

if __name__ == "__main__":
    print("=" * 60)
    print("  findeREC Group Enrollment Demo - LangOrch")
    print("=" * 60)
    print()
    print("  Flow:")
    for num, page, action in STEPS:
        print(f"    Step {num}  {page}")
        print(f"           -> {action}")
    print()

    ensure_backend()
    print("[ok] Backend healthy  (localhost:8000)")

    health = ensure_web_agent()
    print(f"[ok] Playwright agent (mode={health.get('mode', 'unknown')})")

    agent = upsert_web_agent()
    print(f"[ok] Agent registered: {agent['agent_id']}")

    ckp       = json.loads(CKP_FILE.read_text(encoding="utf-8"))
    procedure = import_or_reuse_procedure(ckp)
    print(f"[ok] Procedure ready : {procedure['procedure_id']} v{procedure['version']}")

    print()
    run    = start_run(procedure["procedure_id"], procedure["version"])
    run_id = run["run_id"]
    print(f"[ok] Run started: {run_id}")
    print()

    t0    = time.time()
    final = poll_until_done(run_id, timeout_s=300)
    elapsed = time.time() - t0

    print()
    print(f"  Final status : {final['status']}  ({elapsed:.1f}s)")
    print()
    print("  Screenshots saved to:")
    base = "c:/Users/karup/AGProjects/LangOrch/backend/demo_agents"
    for s in SCREENSHOTS:
        print(f"    {base}/{s}")

    print()
    print(f"  View run -> http://localhost:3000/runs/{run_id}")
    print("=" * 60)
