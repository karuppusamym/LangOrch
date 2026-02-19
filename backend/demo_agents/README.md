# Demo Web Agent

This is a protocol-compatible web agent for LangOrch.

## Endpoints
- `GET /health`
- `POST /execute`

## Run (dry-run mode, default)
```powershell
cd backend
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --host 127.0.0.1 --port 9000
```

Equivalent with explicit env flags:
```powershell
$env:WEB_AGENT_DRY_RUN="true"
$env:WEB_AGENT_HEADLESS="true"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn demo_agents.web_agent:app --app-dir c:/Users/karup/AGProjects/LangOrch/backend/demo_agents --host 127.0.0.1 --port 9000
```

## Register in LangOrch
Use `channel=web` and `base_url=http://127.0.0.1:9000`.

Example body:
```json
{
  "agent_id": "demo-web-agent",
  "name": "Demo Web Agent",
  "channel": "web",
  "base_url": "http://127.0.0.1:9000",
  "resource_key": "web_default",
  "concurrency_limit": 3
}
```

## Optional real browser mode (Playwright)
1. Install package:
```powershell
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m pip install playwright
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m playwright install chromium
```
2. Start in Playwright mode:
```powershell
cd backend/demo_agents
powershell -ExecutionPolicy Bypass -File .\run_playwright_agent.ps1
```

In Playwright mode, actions like `navigate`, `click`, `type`, `wait_for_element`, `extract_text`, `extract_table_data`, and `screenshot` execute against a real browser page.

## End-to-end real automation demo

After starting the Playwright agent, run:

```powershell
cd c:/Users/karup/AGProjects/LangOrch
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe demo_procedures/run_playwright_web_demo.py
```

What this script does:
- Validates backend and agent health
- Registers/updates a dedicated `WEB` agent (`playwright-web-agent`)
- Imports/reuses `demo_procedures/web_playwright_real_demo.ckp.json`
- Creates and polls a run until completion

Agent-only registration helper (without running a demo):

```powershell
cd c:/Users/karup/AGProjects/LangOrch
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe demo_procedures/register_playwright_agent.py
```
