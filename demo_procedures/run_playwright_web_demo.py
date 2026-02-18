from __future__ import annotations

import json
import time
from pathlib import Path

import requests


BASE_URL = "http://localhost:8000/api"
PROCEDURE_FILE = Path(r"c:\Users\karup\AGProjects\LangOrch\demo_procedures\web_playwright_real_demo.ckp.json")


def ensure_backend() -> None:
    response = requests.get(f"{BASE_URL}/health", timeout=5)
    response.raise_for_status()


def ensure_playwright_agent_health() -> dict:
    response = requests.get("http://127.0.0.1:9000/health", timeout=5)
    response.raise_for_status()
    return response.json()


def upsert_playwright_agent() -> dict:
    payload = {
        "agent_id": "playwright-web-agent",
        "name": "Playwright Web Agent",
        "channel": "web",
        "base_url": "http://127.0.0.1:9000",
        "concurrency_limit": 2,
        "resource_key": "web_playwright_default",
        "capabilities": [
            "navigate",
            "click",
            "type",
            "wait_for_element",
            "extract_text",
            "extract_table_data",
            "screenshot",
            "close",
            "wait"
        ]
    }

    response = requests.get(f"{BASE_URL}/agents", timeout=10)
    response.raise_for_status()
    existing = None
    for agent in response.json():
        if agent.get("agent_id") == payload["agent_id"]:
            existing = agent
            break

    if existing:
        update_payload = {
            "status": "online",
            "base_url": payload["base_url"],
            "concurrency_limit": payload["concurrency_limit"],
            "capabilities": payload["capabilities"]
        }
        put_response = requests.put(
            f"{BASE_URL}/agents/{payload['agent_id']}",
            json=update_payload,
            timeout=10,
        )
        put_response.raise_for_status()
        return put_response.json()

    post_response = requests.post(f"{BASE_URL}/agents", json=payload, timeout=10)
    post_response.raise_for_status()
    return post_response.json()


def import_or_reuse_procedure(ckp: dict) -> dict:
    response = requests.get(f"{BASE_URL}/procedures", timeout=10)
    response.raise_for_status()
    for proc in response.json():
        if proc.get("procedure_id") == ckp["procedure_id"] and proc.get("version") == ckp["version"]:
            return proc

    payload = {
        "ckp_json": ckp
    }
    create = requests.post(f"{BASE_URL}/procedures", json=payload, timeout=10)
    create.raise_for_status()
    return create.json()


def create_run(procedure_id: str, version: str) -> dict:
    payload = {
        "procedure_id": procedure_id,
        "procedure_version": version,
        "input_vars": {
            "target_url": "https://example.com"
        }
    }
    response = requests.post(f"{BASE_URL}/runs", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


def wait_for_completion(run_id: str, timeout_seconds: int = 180) -> dict:
    started = time.time()
    terminal = {"succeeded", "completed", "failed", "canceled"}
    last_status = None

    while True:
        response = requests.get(f"{BASE_URL}/runs/{run_id}", timeout=10)
        response.raise_for_status()
        run = response.json()
        status = run.get("status")

        if status != last_status:
            print(f"  status={status}")
            last_status = status

        if status in terminal:
            return run

        if time.time() - started > timeout_seconds:
            raise TimeoutError(f"Run {run_id} did not finish within {timeout_seconds}s")

        time.sleep(2)


if __name__ == "__main__":
    print("== Playwright Web Automation Demo ==")
    ensure_backend()
    print("✓ Backend is healthy")

    agent_health = ensure_playwright_agent_health()
    print(f"✓ Playwright agent is healthy (mode={agent_health.get('mode')})")

    agent = upsert_playwright_agent()
    print(f"✓ Agent registered/updated: {agent['agent_id']} (channel={agent['channel']})")

    ckp = json.loads(PROCEDURE_FILE.read_text(encoding="utf-8"))
    procedure = import_or_reuse_procedure(ckp)
    print(f"✓ Procedure ready: {procedure['procedure_id']} v{procedure['version']}")

    run = create_run(procedure["procedure_id"], procedure["version"])
    run_id = run["run_id"]
    print(f"✓ Run created: {run_id}")

    final = wait_for_completion(run_id)
    print(f"✓ Final status: {final['status']}")
    print(f"Run URL: http://localhost:3000/runs/{run_id}")