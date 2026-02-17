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
$env:WEB_AGENT_DRY_RUN="false"
$env:WEB_AGENT_HEADLESS="true"
C:/Users/karup/AGProjects/LangOrch/.venv/Scripts/python.exe -m uvicorn web_agent:app --app-dir c:/Users/karup/AGProjects/LangOrch/backend/demo_agents --host 127.0.0.1 --port 9000
```

In Playwright mode, actions like `navigate`, `click`, `type`, `wait_for_element`, `extract_text`, `extract_table_data`, and `screenshot` execute against a real browser page.
