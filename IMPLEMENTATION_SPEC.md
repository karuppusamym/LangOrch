# LangOrch — Definitive Implementation Spec

## Product definition

**LangOrch** is an Agentic Automation Platform.

It takes a **CKP (Canonical Knowledge Procedure) JSON** file — a structured, versioned workflow definition — and executes it durably across multiple agent types (Web, Desktop, Email, API, Database, LLM) using **LangGraph** as the durable execution backbone.

It is **not** just a workflow engine. It is a control plane + execution engine + UI that together provide:

- Durable, resumable, replayable workflow execution
- Multi-agent orchestration with safe concurrency (resource locking)
- Human-in-the-loop approval gates
- MCP tool integration
- Step-level idempotency, retry, and error handling
- A web UI for managing procedures, monitoring runs, and acting on approvals
- SQLite by default, configurable to Postgres or SQL Server

**Out of scope (for now):** Observer/O2A capture pipeline, full enterprise RBAC/tenancy.

---

## Architecture layers

```
┌──────────────────────────────────────────────────────────────────┐
│  UI (Next.js + React)                                            │
│  Projects │ Procedures │ Runs │ Approvals │ Agents │ Traces      │
└────────────────────────────┬─────────────────────────────────────┘
                             │ REST + SSE
┌────────────────────────────▼─────────────────────────────────────┐
│  Control Plane API (FastAPI)                                      │
│  ┌─────────┐ ┌──────┐ ┌──────────┐ ┌────────┐ ┌──────────────┐  │
│  │Procedures│ │ Runs │ │Approvals │ │Events  │ │Agent/MCP Reg │  │
│  └─────────┘ └──────┘ └──────────┘ └────────┘ └──────────────┘  │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│  Execution Plane                                                  │
│  ┌──────────┐  ┌────────────────┐  ┌────────────────────────┐    │
│  │ Compiler │→ │ LangGraph      │→ │ Replay-safe executor   │    │
│  │ CKP→IR   │  │ StateGraph     │  │ (idempotency + leases) │    │
│  └──────────┘  └────────────────┘  └────────────────────────┘    │
└────────────────────────────┬─────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│  Workers / Connectors                                             │
│  MCP Client │ Web Agent │ Desktop Agent │ Email │ DB │ LLM       │
└──────────────────────────────────────────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────────────┐
│  Storage                                                          │
│  Platform DB (SQLite/PG/MSSQL) │ Checkpointer │ Artifact Store   │
└──────────────────────────────────────────────────────────────────┘
```

---

## Repository layout

```
langorch/
├── backend/
│   ├── app/
│   │   ├── main.py                 # FastAPI application
│   │   ├── config.py               # Settings (DB, checkpointer, etc.)
│   │   ├── db/
│   │   │   ├── engine.py           # SQLAlchemy engine + session
│   │   │   └── models.py           # ORM models (all tables)
│   │   ├── schemas/                # Pydantic request/response models
│   │   │   ├── procedures.py
│   │   │   ├── runs.py
│   │   │   ├── approvals.py
│   │   │   ├── events.py
│   │   │   └── agents.py
│   │   ├── api/                    # FastAPI routers
│   │   │   ├── procedures.py
│   │   │   ├── runs.py
│   │   │   ├── approvals.py
│   │   │   ├── events.py
│   │   │   ├── agents.py
│   │   │   └── catalog.py
│   │   ├── services/               # Business logic
│   │   │   ├── procedure_service.py
│   │   │   ├── run_service.py
│   │   │   ├── approval_service.py
│   │   │   ├── event_service.py
│   │   │   └── lease_service.py
│   │   ├── compiler/               # CKP → IR
│   │   │   ├── parser.py
│   │   │   ├── validator.py
│   │   │   ├── binder.py
│   │   │   └── ir.py
│   │   ├── runtime/                # IR → LangGraph execution
│   │   │   ├── state.py
│   │   │   ├── graph_builder.py
│   │   │   ├── node_executors.py
│   │   │   ├── executor_wrapper.py
│   │   │   └── hil.py
│   │   ├── connectors/             # External system clients
│   │   │   ├── mcp_client.py
│   │   │   └── agent_client.py
│   │   ├── registry/               # Agent + tool registries
│   │   │   ├── agent_registry.py
│   │   │   └── tool_registry.py
│   │   └── templating/             # {{var}} expansion + expressions
│   │       ├── engine.py
│   │       └── expressions.py
│   ├── requirements.txt
│   └── pyproject.toml
├── frontend/
│   ├── package.json
│   ├── next.config.js
│   ├── tsconfig.json
│   ├── tailwind.config.ts
│   └── src/
│       ├── app/
│       │   ├── layout.tsx          # Root layout + sidebar
│       │   ├── page.tsx            # Dashboard
│       │   ├── projects/page.tsx
│       │   ├── procedures/
│       │   │   ├── page.tsx
│       │   │   └── [id]/page.tsx
│       │   ├── runs/
│       │   │   ├── page.tsx
│       │   │   └── [id]/page.tsx
│       │   ├── approvals/
│       │   │   ├── page.tsx
│       │   │   └── [id]/page.tsx
│       │   └── agents/page.tsx
│       ├── components/
│       │   ├── layout/
│       │   │   ├── Sidebar.tsx
│       │   │   └── Header.tsx
│       │   ├── procedures/
│       │   │   ├── ProcedureList.tsx
│       │   │   └── CKPViewer.tsx
│       │   ├── runs/
│       │   │   ├── RunList.tsx
│       │   │   ├── RunDetail.tsx
│       │   │   └── RunTimeline.tsx
│       │   ├── approvals/
│       │   │   ├── ApprovalInbox.tsx
│       │   │   └── ApprovalDetail.tsx
│       │   └── agents/
│       │       └── AgentInstanceList.tsx
│       └── lib/
│           ├── api.ts              # API client
│           ├── types.ts            # TypeScript types
│           └── sse.ts              # SSE helper
├── ckp_file-main/                  # CKP spec + examples (existing)
├── UNDERSTANDING.md
└── IMPLEMENTATION_SPEC.md
```

---

## Data model (SQLAlchemy ORM, SQLite default)

### Tables

| Table | Purpose |
|-------|---------|
| projects | UI grouping only |
| procedures | Versioned CKP storage |
| runs | Execution tracking |
| run_events | Append-only timeline |
| approvals | HITL decisions |
| step_idempotency | Replay-safe side effects |
| artifacts | Screenshots, downloads, logs |
| agent_instances | Deployed agent capacity |
| resource_leases | Concurrency locks |

### Key rules
- JSON columns: TEXT in SQLite, JSONB in Postgres, NVARCHAR(MAX) in SQL Server — abstracted by the ORM.
- thread_id = run_id (default).
- Never persist secret values; store references only.

---

## API endpoints

| Method | Path | Purpose |
|--------|------|---------|
| POST | /api/procedures | Import CKP JSON |
| GET | /api/procedures | List procedures |
| GET | /api/procedures/{id}/versions | List versions |
| GET | /api/procedures/{id}/{version} | Get specific version |
| POST | /api/runs | Start a run |
| GET | /api/runs | List runs |
| GET | /api/runs/{id} | Run detail |
| POST | /api/runs/{id}/cancel | Cancel run |
| POST | /api/runs/{id}/retry | Retry from checkpoint |
| GET | /api/runs/{id}/events | Run events |
| GET | /api/runs/{id}/stream | SSE live events |
| GET | /api/approvals | List approvals |
| GET | /api/approvals/{id} | Approval detail |
| POST | /api/approvals/{id}/decision | Submit decision |
| GET | /api/agents | List agent instances |
| POST | /api/agents | Register instance |
| GET | /api/catalog/actions | CKP action catalog |

---

## CKP compiler pipeline

```
CKP JSON → parser.py → raw dict
         → validator.py → validated (schema + graph integrity)
         → binder.py → IR with executor bindings
         → graph_builder.py → LangGraph StateGraph
```

---

## Execution model

1. **Compile**: CKP → IR (deterministic, static checks)
2. **Build**: IR → LangGraph StateGraph
3. **Run**: invoke graph with thread_id = run_id, checkpointer persists state
4. **Side effects**: all external calls go through replay-safe wrapper (idempotency table)
5. **HITL**: human_approval nodes call interrupt(), resume via API
6. **Concurrency**: resource leases prevent desktop collisions; queues runs when busy

---

## UI pages

| Page | Features |
|------|----------|
| Dashboard | Run counts, recent activity, pending approvals |
| Projects | List/create projects (UI grouping) |
| Procedures | List, import CKP, view JSON (Monaco), version history |
| Procedure Detail | CKP JSON viewer, start run button, version list |
| Runs | List with status filters, search |
| Run Detail | Live timeline (SSE), node/step progress, artifacts, retry/cancel |
| Approvals | Pending inbox with context preview |
| Approval Detail | Full context, approve/reject/input actions |
| Agents | Instance list, status, capacity, active leases |

---

## What's NOT covered yet (called out)

1. **Workflow Builder UI (React Flow)** — Phase 2; current UI is import/view/monitor only.
2. **Observer/O2A** — Deferred; no screen capture → CKP generation yet.
3. **Enterprise RBAC** — No multi-tenant auth; single-user for now.
4. **Scheduled triggers** — CKP supports cron triggers but the scheduler service is not in scope for initial build.
5. **MCP server hosting** — We build MCP *client* connectors; MCP servers are external.
6. **Agent worker processes** — We define the protocol; actual agent workers (Playwright, WinAppDriver, etc.) need separate implementation.

These are explicitly deferred, not forgotten.
