from __future__ import annotations

import requests


BASE_URL = "http://localhost:8000/api"
AGENT_ID = "playwright-web-agent"


def ensure_backend() -> None:
    response = requests.get(f"{BASE_URL}/health", timeout=5)
    response.raise_for_status()


def upsert_agent() -> dict:
    payload = {
        "agent_id": AGENT_ID,
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

    agents = requests.get(f"{BASE_URL}/agents", timeout=10)
    agents.raise_for_status()
    existing = None
    for agent in agents.json():
        if agent.get("agent_id") == AGENT_ID:
            existing = agent
            break

    if existing:
        update_payload = {
            "status": "online",
            "base_url": payload["base_url"],
            "concurrency_limit": payload["concurrency_limit"],
            "capabilities": payload["capabilities"]
        }
        response = requests.put(f"{BASE_URL}/agents/{AGENT_ID}", json=update_payload, timeout=10)
        response.raise_for_status()
        return response.json()

    response = requests.post(f"{BASE_URL}/agents", json=payload, timeout=10)
    response.raise_for_status()
    return response.json()


if __name__ == "__main__":
    ensure_backend()
    agent = upsert_agent()
    print(f"✓ Agent ready: {agent['agent_id']}")
    print(f"  channel={agent['channel']} base_url={agent['base_url']} status={agent['status']}")