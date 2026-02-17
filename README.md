# LangOrch

LangOrch is an orchestrator-first agentic automation platform that executes **CKP (Canonical Knowledge Procedure)** workflows across channels (WEB, DESKTOP, EMAIL, API, DATABASE, LLM) using a FastAPI control plane and a LangGraph-backed runtime.

This repository currently includes:
- A backend orchestrator (`backend/`) with CKP compile + runtime execution
- A frontend control UI (`frontend/`) for procedures, runs, approvals, agents
- A demo web automation agent (`backend/demo_agents/web_agent.py`) with dry-run + Playwright modes

---

## Current implementation status

## Implemented core capabilities

### Workflow compiler + runtime
- CKP parse → validate → bind pipeline
- Node execution support for:
  - `sequence`, `logic`, `loop`, `parallel`, `processing`, `verification`, `llm_action`, `human_approval`, `transform`, `subflow`, `terminate`
- Runtime dynamic dispatch:
  - Internal actions (local)
  - Agent HTTP dispatch (registered instances)
  - MCP fallback (when configured)

### Durability + replay safety
- LangGraph checkpointer integration with SQLite (`langgraph-checkpoint-sqlite`)
- Thread-based execution context (`thread_id`) used for run invocation
- Step idempotency persistence (`step_idempotency`) with cache reuse path
- Retry flow enhancements:
  - `run_retry_requested` event
  - Retry preparation API path
  - Retry fallback resume from `last_node_id` when applicable

### Multi-agent safety
- Resource lease acquisition/release around agent-dispatched steps
- Concurrency control through `resource_key` + `concurrency_limit`

### Human-in-the-loop
- Approval model + APIs
- Runtime pause behavior (`waiting_approval`) and resume support via approval decision injection

### Observability + run tracking
- Run timeline events + SSE stream
- Step-level events (`step_started`, `step_completed`)
- Subflow events (`subflow_started`, `subflow_completed`)
- Artifact events (`artifact_created`)

### Artifact persistence
- Automatic extraction from step results (`artifact`, `artifacts`, `artifact_uri`, `uri`, screenshot placeholder)
- Persistence to `artifacts` table
- API endpoint: `GET /api/runs/{run_id}/artifacts`
- Frontend run detail artifact rendering + live refresh on SSE artifact events

### Frontend management features
- Procedure listing/version navigation
- Procedure version detail/edit/delete
- Run filtering/sorting/date-range + cleanup/delete
- Run detail timeline with live updates
- Approval inbox/detail
- Agents listing
- Live artifact notice on run detail when new artifacts arrive

---

## Architecture overview

- **Backend**: FastAPI + SQLAlchemy async + SQLite
- **Runtime**: LangGraph state graph execution
- **Frontend**: Next.js App Router + TypeScript
- **Automation demo**: Playwright-capable web agent

Key backend modules:
- `backend/app/compiler/*` — CKP parser/validator/binder/IR
- `backend/app/runtime/*` — graph builder + node executors
- `backend/app/services/*` — run/procedure/approval/event/lease services
- `backend/app/api/*` — REST APIs

---

## API surface (high level)

### Procedures
- `POST /api/procedures`
- `GET /api/procedures`
- `GET /api/procedures/{id}/versions`
- `GET /api/procedures/{id}/{version}`
- `PUT /api/procedures/{id}/{version}`
- `DELETE /api/procedures/{id}/{version}`

### Runs
- `POST /api/runs`
- `GET /api/runs`
- `GET /api/runs/{id}`
- `GET /api/runs/{id}/events`
- `GET /api/runs/{id}/stream`
- `GET /api/runs/{id}/artifacts`
- `POST /api/runs/{id}/cancel`
- `POST /api/runs/{id}/retry`
- `DELETE /api/runs/{id}`
- `DELETE /api/runs/cleanup/history`

### Approvals / Agents / Catalog
- `GET /api/approvals`
- `GET /api/approvals/{id}`
- `POST /api/approvals/{id}/decision`
- `GET /api/agents`
- `POST /api/agents`
- `GET /api/actions`

---

## Local setup

## Prerequisites
- Python 3.11+
- Node.js 18+
- npm

## Backend setup
```powershell
cd backend
python -m venv ..\.venv
..\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

Run backend:
```powershell
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Health check:
```powershell
Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/health
```

## Frontend setup
```powershell
cd frontend
npm install
npm run dev -- -p 3000
```

Build check:
```powershell
cd frontend
npm run build
```

## Demo web agent setup (optional)
```powershell
cd .
.\.venv\Scripts\Activate.ps1
pip install "playwright>=1.50"
python -m playwright install chromium
```

Run demo agent:
```powershell
# Dry-run mode (default)
.\.venv\Scripts\python.exe -m uvicorn demo_agents.web_agent:app --app-dir backend --host 127.0.0.1 --port 9000

# Real Playwright mode
$env:WEB_AGENT_DRY_RUN="false"
.\.venv\Scripts\python.exe -m uvicorn demo_agents.web_agent:app --app-dir backend --host 127.0.0.1 --port 9000
```

---

## Important operational notes

- Do not run `next dev` and `next build` simultaneously against the same `frontend/.next` directory.
- If dev chunk errors occur, stop dev server, clear `frontend/.next`, and restart dev.
- Browser extension `contentScript.js` console errors are external to this app.

---

## Repository docs

- **Product understanding**: [UNDERSTANDING.md](UNDERSTANDING.md) — Core requirements, CKP contract, architecture decisions
- **Definitive spec**: [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md) — Complete technical specification, architecture layers, repository layout
- **Implementation status**: [IMPLEMENTATION_STATUS.md](IMPLEMENTATION_STATUS.md) — CKP spec vs code matrix, gap analysis, quick wins
- **Future roadmap**: [FUTURE_PLAN.md](FUTURE_PLAN.md) — Code-aligned roadmap, domain-specific plans, sprint sequence
- **CKP syntax reference**: [ckp_file-main/ckp_file_syntex.txt](ckp_file-main/ckp_file_syntex.txt) — Complete CKP JSON schema with all node types and policies
- **Sample CKP workflows**: [ckp_file-main/*.json](ckp_file-main/) — Multi-agent workflow examples
- **Demo agent guide**: [backend/demo_agents/README.md](backend/demo_agents/README.md) — Web automation agent setup and usage

---

## Development quick links

- [Implementation Status Matrix](IMPLEMENTATION_STATUS.md#ckp-specification-vs-implementation-matrix) — See exactly what's implemented vs spec
- [Critical Gaps](FUTURE_PLAN.md#critical-implementation-gaps-ckp-spec-vs-current-code) — High-priority missing features
- [Sprint Plan](FUTURE_PLAN.md#suggested-execution-order-for-immediate-next-sprints) — 7-sprint roadmap for completion
- [Established Patterns](FUTURE_PLAN.md#established-patterns-and-architectural-strengths-use-these-as-templates) — Proven code patterns to follow
- [Quick Wins](IMPLEMENTATION_STATUS.md#quick-win-priorities-sorted-by-impacteffort) — High-impact, lower-effort improvements
