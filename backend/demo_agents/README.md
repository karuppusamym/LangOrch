# Demo Agents

This directory contains demonstration agent implementations for LangOrch.

---

## Agents

### 1. Local Playwright Agent (`web_agent.py`)
A full-featured browser automation agent using real Playwright navigation.

**Capabilities (tool type):** `navigate`, `click`, `type`, `wait_for_element`, `extract_text`, `extract_table_data`, `select_all_text`, `get_attribute`, `screenshot`, `close`

**Start:**
```powershell
powershell -ExecutionPolicy Bypass -File .\run_playwright_agent.ps1
```
- Runs on `http://127.0.0.1:9000`
- Channel: `web`
- Resource key: `web_default`

**Configurable environment variables (multi-agent tests):**
- `WEB_AGENT_ID`
- `WEB_AGENT_NAME`
- `WEB_AGENT_PORT`
- `WEB_AGENT_CHANNEL` (default: `web`)
- `WEB_AGENT_POOL_ID` (default: `web_pool_1`)
- `WEB_AGENT_RESOURCE_KEY` (default: `web_default`)
- `WEB_AGENT_CONCURRENCY` (default: `1`)

**Start 5 WEB agents in one pool (dry-run):**
```powershell
powershell -ExecutionPolicy Bypass -File .\run_5_web_agents.ps1
```

**Start 5 WEB agents in different pools (dry-run):**
```powershell
powershell -ExecutionPolicy Bypass -File .\run_5_web_agents_split_pools.ps1
```

Note: Dispatcher currently selects the first sorted pool key for a channel before doing round-robin in that pool. Using a single shared pool is recommended for full utilization in load tests.

**Endpoints:** `GET /health`, `GET /capabilities`, `POST /execute`

---

### 2. Hybrid Tools & Workflow Demo Agent (`hybrid_agent.py`)
Demonstrates **both execution paradigms** in a single agent:
- **Granular tools** — fast, step-by-step atomic actions
- **One-shot workflow** — slow long-running macro that executes independently

**Capabilities:**
| Name | Type | Duration |
|---|---|---|
| `browser.navigate` | tool | ~0.5s |
| `browser.click` | tool | ~0.5s |
| `browser.type` | tool | ~0.5s |
| `run_full_salesforce_login` | **workflow** | ~15s |

**Start:**
```powershell
powershell -ExecutionPolicy Bypass -File .\run_hybrid_agent.ps1
```
- Runs on `http://127.0.0.1:9005`
- Channel: `hybrid`
- Resource key: `hybrid_default`

---

## Register in LangOrch
Go to `http://localhost:3000/agents` → **Register Agent** → fill URL → click **Fetch Caps** to auto-populate structured capabilities.

Or via API:
```json
POST /api/agents
{
  "name": "Local Playwright Agent",
  "channel": "web",
  "base_url": "http://127.0.0.1:9000",
  "concurrency_limit": 1
}
```

---

## Sample CKP File
`sample_all_options.ckp.json` — A comprehensive procedure JSON covering every supported node type:
`sequence`, `transform`, `verification`, `logic`, `llm_action`, `human_approval`, `loop`, `processing`, `parallel`, `subflow`, `terminate`

Use it as a reference when building new procedures.

---

## End-to-End Demo
```powershell
cd c:/Users/karup/AGProjects/LangOrch
.\.venv\Scripts\python.exe demo_procedures/run_playwright_web_demo.py
```
