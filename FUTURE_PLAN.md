# LangOrch Future Plan (Code-Aligned)

Last updated: 2026-02-22 (Batch 34: 4 enhancements —
**Enhancement 1** Artifact metadata: `name` / `mime_type` / `size_bytes` columns added to `artifacts` table, `ArtifactOut` schema, `create_artifact()` signature, and SQLite idempotent migrations — artifact UI can show original filename, type, and size;
**Enhancement 2** `GET /api/queue`: job queue visibility endpoint — grouped counts by status, total pending/running/done/failed, next 20 pending jobs with priority and availability timestamp;
**Enhancement 3** `GET /api/agents/pools`: per-pool stats — agent count, status breakdown, aggregate concurrency limit, active lease count, available capacity, circuit-open agent count;
**Enhancement 4** WorkflowBuilder 3-tier node architecture: palette reorganised into Deterministic (Blue) / Intelligent (Purple) / Control (Orange) category groups with color-coded section headers; each node card shows a category badge; color scheme updated to category-consistent shades; 3 workflow templates added: Invoice Processing, Customer Support, Contract Review — one-click load into the canvas)

This roadmap is updated from direct code analysis of current backend, runtime, API, and frontend implementation.

---

## Canonical remaining gaps (single source of truth)

Use this section as the authoritative snapshot of what is still missing. If any later section conflicts with this list, this list wins.

| Gap | Current state | Priority |
|-----|---------------|----------|
| External observability backend | Prometheus endpoint + Pushgateway push are implemented; Prometheus text format with proper label syntax now correct; full OpenTelemetry traces/log shipping/correlation backend is pending | P0 |
| Event-bus trigger adapters | Cron/webhook/file-watch/manual are implemented; Kafka/SQS-style consumer adapters are pending | P1 |
| Multi-tenant isolation | Single-tenant model; no tenant-scoped data partitioning and policy enforcement | P1 |
| Procedure promotion/canary/rollback | Versioning + status lifecycle (PATCH `/status` endpoint) done; controlled environment promotion and canary/blue-green rollout are pending | P1 |
| LLM fallback-model routing | Hard budget abort (`max_cost_usd`) now implemented; fallback-model routing policy (cost-based model selection) is pending | P1 |
| Compliance controls | No PII tokenization pre-LLM, GDPR erase flow, or policy-as-code compile checks | P2 |
| Agent pool capacity signals | `pool_id` + round-robin + `GET /api/agents/pools` stats (agent count, active leases, available capacity, circuit-open count) done (**Batch 34**); `pool_saturated` event emission and autoscale hint are pending | P2 |
| Test hardening breadth | Strong unit coverage + core Playwright flows; broader load/soak and failure-path e2e coverage are pending | P2 |

---

## Definition of Done (Production)

LangOrch is considered **production-ready** when all items below are true:

- [x] **Security**: AuthN/AuthZ enabled; role-based approvals enforced; every action attributable to an identity
- [x] **Reliability/HA**: scheduler/trigger firing is HA-safe under multiple replicas (no double-fire); run execution is idempotent under concurrency
- [x] **Scalability**: durable worker model exists (API separate from workers); horizontal scaling does not duplicate work
- [x] **Data**: production database + migrations + backups are in place; hot-path indexes exist
- [ ] **Observability**: metrics/traces/logs exported to an external backend; on-call can debug a run end-to-end (pending full OpenTelemetry backend)
- [x] **Quality gates**: CI blocks regressions (lint, type-check, tests, build) and core UI flows have e2e coverage

See **Production readiness checklist (P0/P1)** below for concrete deliverables.

---

## Architectural Philosophy — Hybrid Automation

### Core premise

Most real-world processes are neither fully automatable by rules nor fully delegatable to AI. They contain **predictable structural components** (look up a record, call an API, write a file) and **ambiguous judgment components** (interpret unstructured text, assess risk, draft a response). LangOrch is built on the premise that the right architecture **explicitly models both** and lets them compose cleanly — rather than forcing every step through an LLM or hard-coding every action into rule logic.

The central design goal: **reliable orchestration that escalates to intelligence only where intelligence is needed,** and falls back to humans only where neither algorithm nor model is sufficient.

---

### The three-tier node model

Every CKP node belongs to exactly one of three tiers. The tier is not cosmetic — it determines execution semantics, failure modes, cost profile, and how the platform routes and monitors the step.

#### 🔵 Deterministic tier (Blue)
> *Fast, reliable, auditable. Same input always produces the same output.*

| Node type | Role |
|-----------|------|
| `sequence` | Ordered API call, HTTP request, or external system integration |
| `processing` | Structured data validation, transformation, computation |
| `transform` | Pure state rewrite — filter, map, reshape JSON without I/O |
| `subflow` | Invoke another CKP procedure as a composable unit |

**Properties:**
- **Predictable cost** — no token spend, no variable latency from model inference
- **Testable** — input/output pairs can be captured and replayed in CI
- **Safe to retry** without concern for idempotency at the LLM level
- **Auditability is complete** — every step produces a structured event with full inputs and outputs recorded

**When to use:** Any step where the correct logic is fully known, expressible as code or an API call, and must behave identically every time. This is the default choice — reach for a deterministic node first.

---

#### 🟣 Intelligent tier (Purple)
> *Adaptive, reasoning-capable. Output varies based on context and model judgment.*

| Node type | Role |
|-----------|------|
| `llm_action` | LLM call with prompt template, model selection, structured output, and cost tracking |

**Properties:**
- **Context-sensitive** — the same template can produce different outputs for different inputs; this is intentional and desirable
- **Costly** — token spend is tracked per run; `global_config.max_cost_usd` hard-aborts the run before overspend
- **Non-deterministic** — temperature/sampling means outputs vary; use structured output schemas and verification nodes to constrain variance
- **Can reason across unstructured data** — classify text, extract entities, summarise documents, generate drafts
- **Requires guardrails** — should be followed by a `verification` or `logic` node whenever the output drives a consequential branch

**When to use:** Steps involving unstructured or ambiguous input, natural language understanding, content generation, semantic classification, or anything where the correct answer cannot be expressed as a deterministic rule. Use sparingly and always account for cost and latency.

---

#### 🟠 Control tier (Orange)
> *Orchestration logic. Routes execution, manages concurrency, enforces governance.*

| Node type | Role |
|-----------|------|
| `logic` | Conditional branching on workflow state (`on_true` / `on_false` / rules list) |
| `loop` | Iterate over a collection or repeat until a condition is met (`loop_body`) |
| `parallel` | Fan-out — execute multiple branches concurrently and join results |
| `verification` | Assert that a previous step's output meets a schema or constraint (`on_pass` / `on_fail`) |
| `human_approval` | Pause execution pending a decision from a named approver (`on_approve` / `on_reject` / `on_timeout`) |
| `terminate` | Explicitly end the run with a declared terminal status |

**Properties:**
- **Stateless logic** — control nodes operate on workflow state already present; they do not call external services
- **Zero cost** — no token spend; fast
- **Composable governance** — `verification` and `human_approval` are the enforcement layer between tiers; they catch errors from either deterministic or intelligent steps before they propagate
- **Human-in-the-loop boundary** — `human_approval` is the explicit handoff point where the system acknowledges it cannot proceed autonomously

**When to use:** Wherever the workflow needs to branch, iterate, run things in parallel, validate results, or wait for a human decision. Control nodes are the connective tissue of the graph — they are not doing work themselves, they are directing where work goes next.

---

### How the tiers compose

Effective workflows follow a pattern: **deterministic nodes gather and prepare data → intelligent nodes reason over it → control nodes validate and route the result → deterministic nodes act on the decision.**

```
[sequence: fetch invoice]
        │
[llm_action: extract fields]        ← intelligent: parse unstructured PDF
        │
[verification: validate schema]     ← control: enforce required fields present
        │              │
     (pass)         (fail)
        │              └──[sequence: flag for manual review]
[logic: amount > $10k?]             ← control: deterministic rule
        │              │
     (true)         (false)
        │              └──[sequence: auto-approve + log]
[human_approval: manager sign-off]  ← control: governance gate
        │              │
    (approve)      (reject)
        │              └──[sequence: notify requester]
[sequence: post to ERP]             ← deterministic: reliable write
        │
[terminate: success]
```

This pattern delivers three compound properties that neither pure-rule nor pure-LLM systems achieve alone:

| Property | How it is achieved |
|----------|--------------------|
| **Reliability** | Structural steps (API calls, writes) use deterministic nodes — no model variance in consequential I/O |
| **Adaptability** | Intelligent nodes handle the steps where rules would be brittle — unstructured input, natural language, ambiguous classification |
| **Accountability** | Verification and human_approval nodes create explicit checkpoints; every decision has a recorded event in the run timeline |

---

### Design rules derived from this philosophy

1. **Default to deterministic.** If a step can be expressed as an API call or a data transformation, it should be a `sequence`, `processing`, or `transform` node — not an `llm_action`. LLMs are expensive, slow, and non-deterministic.

2. **Isolate intelligence.** `llm_action` nodes should have a single, focused responsibility (extract, classify, summarise, draft). A node that both extracts *and* decides *and* writes is a smell — split it into a deterministic extraction, an intelligent interpretation, and a deterministic write.

3. **Always verify model output before routing.** Any `llm_action` whose output drives a `logic` branch or a write to an external system should be followed by a `verification` node. This is the primary mechanism for catching model errors before they cause downstream damage.

4. **Make the human boundary explicit.** `human_approval` nodes are not a fallback — they are a deliberate governance policy decision. If a workflow requires human sign-off for values above a threshold or for a specific action class, that constraint should be visible in the graph, not buried in application code.

5. **Cost is a first-class concern.** Set `global_config.max_cost_usd` on every production procedure that contains `llm_action` nodes. The platform will hard-abort the run with a `budget_exceeded` event before overspend occurs.

6. **Compose horizontally, not vertically.** A `subflow` node that calls a focused sub-procedure is better than one monolithic graph. Sub-procedures can be versioned, tested, and reused independently.

---

### Operational properties of the hybrid model

| Concern | Deterministic nodes | Intelligent nodes | Control nodes |
|---------|--------------------|--------------------|---------------|
| Latency | Low (bound by external API) | High (model inference) | Near-zero |
| Cost | Zero token spend | Per-token billing | Zero token spend |
| Retry safety | Safe (idempotency key controls dedup) | Caution — same prompt may produce different output | Safe — no side effects |
| Observability | Full structured I/O in run events | Prompt + completion recorded; token counts tracked | Branch decision recorded in run events |
| Failure mode | Network/API errors — well-understood | Hallucination, schema violation, token limit — needs verification guard | Evaluation error on state shape |
| Test strategy | Unit test with fixed fixtures | Snapshot test prompt+schema; integration test with live model | Logic unit test with state fixtures |

---

### Agent Pool Routing Strategy

When a step requires an agent executor, the orchestrator automatically routes the task to an available agent based on a specific selection algorithm (`_find_capable_agent` in `executor_dispatch.py`):

1. **Capability Matching**: The system filters the registry for "online" agents whose `channel` matches the node's declared agent channel, and whose `capabilities` list includes the specific action being requested (or `*`).
2. **Health Check**: Agents with an open circuit breaker (due to consecutive failures) are excluded from the candidate pool until the `_CIRCUIT_RESET_SECONDS` timeout expires.
3. **Pool Grouping**: The remaining candidate agents are grouped by `pool_id` (forming an implicit `standalone` pool if `pool_id` is null). The system selects the numerically/alphabetically first pool that contains at least one healthy, capable agent.
4. **Round-Robin Distribution**: Within the selected pool, the system maintains an in-memory counter (`_pool_counters`) to distribute tasks using a monotonic round-robin strategy (`counter % pool_size`). This ensures equitable load distribution among all identical agents in a saturated pool.

---

## Current implementation baseline (what is already done)

### Strongly implemented
- CKP compile pipeline (parse → validate → bind) and runtime execution graph
- Runtime executors for all 11 node types: `sequence`, `logic`, `loop`, `parallel`, `subflow`, `processing`, `verification`, `llm_action`, `human_approval`, `transform`, `terminate`
- Checkpoint-enabled invocation with SQLite checkpointer and thread-based context
- Step idempotency persistence + cached replay path
- Agent dispatch with resource lease acquisition/release
- Retry with exponential backoff (max_retries, retry_delay_ms, backoff_multiplier)
- Run event timeline + SSE stream + step/subflow/artifact events
- Artifact extraction/persistence + artifacts API + frontend rendering; artifact files stored under `artifacts/{run_id}/` — run-scoped, no cross-run file collision
- `_build_template_vars()` in `node_executors.py` — injects `{{run_id}}` and `{{procedure_id}}` as built-in variables into all node executor template contexts; usable in any CKP step param (e.g. `"path": "artifacts/{{run_id}}/screenshot.png"`)
- Core CRUD APIs for procedures, runs, approvals, agents, projects, and leases — 35+ endpoints total
- **Projects API**: full CRUD (`GET/POST/PUT/DELETE /api/projects`), project filter on procedure list
- **Agent management**: register, update (status/capabilities), delete agents; background health polling every 60 s
- **Leases API**: `GET /api/leases` + `DELETE /api/leases/{id}` — stale lease force-release implemented
- **Diagnostics API**: `GET /api/runs/{id}/diagnostics` — idempotency entries, active leases, event counts, retry markers
- **Checkpoint introspection API**: `GET /api/runs/{id}/checkpoints` + `GET /api/runs/{id}/checkpoints/{cpid}`
- **Secrets provider abstraction**: all 4 providers complete — `EnvironmentSecretsProvider`, `VaultSecretsProvider` (AppRole, KV v1/v2, namespace), `AWSSecretsManagerProvider` (boto3, JSON field extraction, LocalStack), `AzureKeyVaultProvider` (DefaultAzureCredential, key normalisation) + `CachingSecretsProvider` TTL decorator + `provider_from_config` factory
- **Event redaction**: recursive sensitive field sanitization (password, token, api_key, secret, etc.)
- **In-memory metrics**: counters/histograms + `GET /api/runs/metrics/summary` endpoint
- **Graph extraction API**: `GET /api/procedures/{id}/{version}/graph` → React Flow-compatible nodes/edges
- **Workflow graph viewer (frontend)**: interactive React Flow with custom CKP nodes, color-coding, minimap, zoom/pan
- **549 backend tests** — all passing (current baseline)
- **Durable worker model**: `app/worker/` package with `loop.py` (poll/claim/execute/stall-reclaim), `heartbeat.py` (lock renewal + cancel bridge), `worker_main.py` (standalone entrypoint), `enqueue_run` (new runs) + `requeue_run` (approval-resume + retry, SELECT-UPDATE-or-INSERT avoiding UNIQUE constraint violation on `run_jobs.run_id`); embedded in server via `asyncio.create_task`; SQLite optimistic-locking and PostgreSQL `FOR UPDATE SKIP LOCKED` dialects both implemented
- **HA-safe scheduling** (`app/runtime/leader.py`): DB-backed `LeaderElection` class; `SchedulerLeaderLease` table; INSERT-wins / UPDATE-steal / renewal (TTL 60s, renew 15s); APScheduler sync, `_fire_scheduled_trigger`, `_file_watch_trigger_loop`, and `_approval_expiry_loop` all skip when not leader — no double-fire under multiple replicas
- **Artifact retention/TTL** (`ARTIFACT_RETENTION_DAYS=30`): `_artifact_retention_loop()` background sweep (leader-gated, hourly) deletes `artifacts/{run_id}/` folders for terminal runs older than the configured threshold; orphaned folders pruned by mtime; `POST /api/artifacts-admin/cleanup` manual trigger + `GET /api/artifacts-admin/stats` for disk usage
- **Frontend e2e tests**: 26 Playwright e2e tests across 4 spec files (`navigation.spec.ts`, `procedures.spec.ts`, `runs.spec.ts`, `approvals.spec.ts`) — page-load smoke tests, UI import flow, run creation, timeline verification, approval approve/reject flow; `playwright.config.ts` auto-starts dev server; fixtures + shared helpers
- **681 backend tests** — all passing after Batch 30
- 12-route frontend: Dashboard, Procedures (list/detail/edit/version-diff), Runs (list/detail/timeline/bulk-ops), Approvals (inbox/detail/SSE-live), Agents, Projects, Leases
- **Dark mode**: system-preference-aware toggle in header, persisted to localStorage
- **Retry with modified inputs**: run detail retry button opens variables editor pre-filled with original inputs
- **Procedure version diff**: side-by-side CKP JSON diff viewer with line-level LCS comparison
- **Artifact preview**: inline text/JSON preview + download button for all artifacts
- **Bulk operations**: multi-select checkboxes on runs list with bulk cancel/delete + confirmation
- **SSE for approvals**: real-time approval push via `GET /api/approvals/stream` (replaces 10s polling)
- **Configurable redaction**: `build_patterns()` merges CKP `audit_config.redacted_fields` with default patterns

### Partially implemented
- Telemetry fields: `track_duration` and `track_retries` emitted in step events; `custom_metrics` recorded; not yet exported to external backends
- AuthN/AuthZ is implemented as opt-in (`AUTH_ENABLED`) and guards mutating endpoints; remaining hardening is enabling-by-default in production with centralized identity provider integration (OIDC/SSO) and stricter scope governance
- Agent pool model is implemented with `pool_id` and deterministic per-pool round-robin; remaining work is capacity/saturation signaling and advanced routing policies

### Not yet implemented (high impact gaps)
- **External observability stack** — Prometheus endpoint and Pushgateway push are implemented, but full OpenTelemetry traces/log shipping/correlation backend is still pending
- **Event-bus trigger adapters** — cron/webhook/file-watch are implemented; Kafka/SQS-style consumer adapters are still pending
- **Multi-tenant governance** — project-level operations are implemented, but tenant-scoped isolation and policy enforcement are not yet implemented

---

## Gap analysis by domain

## 1) Execution correctness and recoverability
### Current — UPDATED 2026-02-21 (Batch 28)
- ✅ Durable graph execution with LangGraph SQLite checkpointer
- ✅ `GET /api/runs/{id}/diagnostics` — idempotency entries, active leases, event counts, retry markers
- ✅ `GET /api/runs/{id}/checkpoints` — full checkpoint introspection
- ✅ Retry with exponential backoff (max_retries, delay_ms, backoff_multiplier) enforced globally
- ✅ `_build_template_vars()` — `{{run_id}}` and `{{procedure_id}}` available as built-in template variables in every CKP step parameter
- ✅ Run-scoped artifact storage — `artifacts/{run_id}/` subfolder per run; no cross-run collisions

### Remaining gaps
- ~~Error handlers (`recovery_steps`, `fallback_node`, `retry_policy`) are parsed into IR but NOT executed~~ → ✅ Fully implemented (Batches 7 + 15)
- ~~Step-level `timeout_ms` not enforced~~ → ✅ `asyncio.wait_for` wraps all three binding paths (internal, agent_http, mcp_tool)
- ~~`wait` action is a no-op placeholder~~ → ✅ `wait_ms` / `wait_after_ms` both call `asyncio.sleep`
- ~~Custom `idempotency_key` templates not evaluated~~ → ✅ Jinja2 rendering applied

### Next implementation items
- ✅ **[Batch 14]** `IRStep.retry_config` dict for per-step retry policy override (max_retries/delay_ms/backoff_multiplier)
- ✅ **[Batch 14]** `IRLlmActionPayload.retry` dict for per-node LLM retry override
- ✅ **[Batch 14]** `is_checkpoint` selective forcing: `_checkpoint_node_id` marker injected by `make_fn`, detected by streaming execution loop, `checkpoint_saved` event emitted
- ✅ **[Batch 15]** `notify_on_error=True` in `IRErrorHandler` emits `step_error_notification` event + fires alert webhook
- ✅ **[Batch 16]** Server-side `input_vars` validation at `POST /api/runs` — required, type, regex, allowed_values, min/max enforced via `app/utils/input_vars.py`; returns HTTP 422 with per-field error map
- ✅ **[Batch 16]** Step-level `execution_mode=dry_run` — `agent_http` and `mcp_tool` bindings skipped; `dry_run_step_skipped` event emitted; `execution_mode` now propagated through `OrchestratorState`
- ✅ **[Batch 7]** `IRErrorHandler` recovery_steps, fallback_node, retry, ignore, fail, screenshot_and_fail all dispatched
- ✅ **[Batch 10]** `asyncio.wait_for(step.timeout_ms)` wraps internal + MCP + agent_http calls; emits `step_timeout` event
- ✅ **[Batch 10]** `asyncio.sleep(wait_ms)` / `asyncio.sleep(wait_after_ms)` enforced per step

## 2) Automation and orchestration triggers
### Current — UPDATED 2026-02-21 (Batch 20 + Batch 22 + Batch 29)
- ✅ Trigger registry model + APIs
- ✅ Cron scheduler worker (APScheduler) for scheduled triggers
- ✅ Webhook trigger API with HMAC verification + dedupe window + max_concurrent_runs
- ✅ File-watch trigger loop
- ✅ Trigger provenance on runs (`trigger_type`, `triggered_by`) visible in UI
- ✅ **HA-safe scheduling (Batch 29)** — `LeaderElection` class in `app/runtime/leader.py`; DB row (`scheduler_leader_leases`) with INSERT-wins / UPDATE-steal / renewal; TTL 60s, renew every 15s; APScheduler sync loop + `_fire_scheduled_trigger` + `_file_watch_trigger_loop` + `_approval_expiry_loop` all skip execution when not leader; `SchedulerLeaderLease` ORM model; Alembic migration updated; 18 new tests

### Remaining gaps
- Event-driven triggers beyond webhook/file-watch (if adopting external event bus)
- Trigger operational tooling: pause/resume per trigger, per-trigger backoff/retry visibility, dead-lettering

### Next implementation items
- ~~Make scheduler HA-safe (leader election or external scheduler)~~ → ✅ Done (Batch 29)
- Add event trigger adapter (e.g., queue/topic consumer) with the same dedupe/concurrency controls
- Add trigger-run audit dashboard + export

## 3) Security and governance
### Current — UPDATED 2026-02-19 (Batch 21)
- ✅ Secrets provider abstraction: `EnvironmentSecretsProvider`, `VaultSecretsProvider` (AppRole + KV v1/v2 + namespace), `AWSSecretsManagerProvider` (boto3, JSON field extraction, LocalStack endpoint), `AzureKeyVaultProvider` (DefaultAzureCredential, underscore→hyphen normalisation); `CachingSecretsProvider` TTL decorator; `provider_from_config` factory
- ✅ Event redaction: recursive sensitive field sanitization active in all event emission paths

### Remaining gaps
- Auth is currently opt-in (`AUTH_ENABLED=false` default), so production deployments must enforce enablement and secret/key rotation policy
- Role model is global; project-scoped RBAC and enterprise IdP integration remain pending
- ~~Redaction policy is hardcoded key-name patterns~~ — ✅ Configurable via `build_patterns(extra_fields)` + `emit_event(extra_redacted_fields=...)`

### Next implementation items
- Harden auth for production rollout (enable-by-default profiles, OIDC integration, project-scoped RBAC)
- ~~Implement AWS Secrets Manager and Azure Key Vault provider adapters~~ → ✅ Done (Batch 21)
- ~~Make redaction field list configurable from `global_config.audit_config`~~ — ✅ Implemented via `build_patterns()` + `emit_event(extra_redacted_fields=...)`

## 4) Observability and operations
### Current — UPDATED 2026-02-17
- ✅ Event timeline + SSE stream working
- ✅ In-memory metrics (counters + histograms) with `GET /api/runs/metrics/summary`
- ✅ Run diagnostics API (`GET /api/runs/{id}/diagnostics`) — idempotency, lease, event, retry data
- ✅ `graph_service.py` provides React Flow graph data for workflow visualization
- ✅ `GET /api/leases` + `DELETE /api/leases/{id}` — stale lease force-release implemented with UI on /leases page

### Remaining gaps
- Metrics are process-local in-memory — not persistent, not exported to external Prometheus/OpenTelemetry
- ~~`sla.max_duration_ms` not tracked~~ → ✅ Node-level SLA tracked, `sla_breached` events emitted (Batch 13)
- ~~No alert hooks for failed/stuck runs~~ → ✅ `_fire_alert_webhook` on `run_failed` (Batch 13)
- ~~`telemetry` fields parsed but not acted on~~ → ✅ `track_duration` + `track_retries` emitted in step events; `custom_metrics` recorded (Batches 10 + 11)

### Next implementation items
- Export metrics to external Prometheus/OpenTelemetry backend (in-memory only; endpoint exists)
- Add artifact retention/cleanup policy: configurable TTL + background sweep of `artifacts/{run_id}/` folders older than N days

## 5) Frontend operations UX
### Current — UPDATED 2026-02-17
- ✅ 12 routes: Dashboard, Procedures (list/detail/edit/version-diff), Runs (list/detail/timeline/bulk-ops), Approvals (inbox/detail/SSE-live), Agents, Projects, Leases
- ✅ Workflow graph viewer implemented with React Flow, custom CKP node types, minimap, color-coding
- ✅ Live run timeline with SSE subscription + event deduplication + auto-scroll
- ✅ Artifacts list with auto-refresh on `artifact_created` SSE events
- ✅ Procedure CKP JSON edit inline + version management
- ✅ Runs: filters, date range, quick presets, bulk cleanup, cancel/delete
- ✅ Projects CRUD page: list, create, inline-edit, delete
- ✅ Agents page: register, capabilities checkboxes, toggle online/offline, delete
- ✅ Leases page: list active leases, force-release with confirmation
- ✅ All destructive actions use in-app `ConfirmDialog` — no browser `confirm()`/`alert()` calls
- ✅ `masteragent` channel available in agent registration dropdown

### Remaining gaps
- ~~No UI for `GET /api/runs/{id}/diagnostics` data~~ — ✅ Diagnostics tab in run detail page
- ~~No UI for `GET /api/runs/metrics/summary`~~ — ✅ Dashboard metrics panel with histograms
- ~~`createRun` always sends `{}` for `input_vars`~~ — ✅ Input variables form with full validation
- ~~No retry-path overlay in timeline~~ — ✅ Retry-with-modified-inputs modal on failed runs
- ~~No LLM/agent invocation detail panel (model used, tokens, latency)~~ → ✅ `llm_usage` event structured display (model chip, prompt/completion token pills, duration_ms; Batch 24)
- ~~No approval SLA/escalation indicators~~ → ✅ Overdue red highlight + ⚠ OVERDUE badge on both approvals list and detail pages (Batch 24)
- ~~Duplicate UI components: `StatusBadge` defined independently~~ — ✅ Extracted to `src/components/shared/`

### Next implementation items
- ~~Add diagnostics tab to run detail page using existing `GET /api/runs/{id}/diagnostics`~~ — ✅ Done
- ~~Add metrics card to dashboard using `GET /api/runs/metrics/summary`~~ — ✅ Done
- ~~Add input variables form modal at run-start that reads `variables_schema` from the procedure~~ — ✅ Done
- ~~Extract `StatusBadge` and `ApprovalStatusBadge` into `src/components/shared/`~~ — ✅ Done
- ~~Add LLM/agent step detail panel (model, tokens, latency)~~ → ✅ Done (Batch 24)
- ~~Add approval SLA/escalation indicators~~ → ✅ Done (Batch 24)

## 6) Quality and delivery discipline
### Current — UPDATED 2026-02-19 (Batch 21)
- ✅ 278 backend tests (Batch 13): retry config, step_timeout events, SLA breach, alert webhook, Prometheus, shared UI
- ✅ **312 backend tests** (Batch 14): explain service (19), step retry config (5), LLM retry (3), is_checkpoint marker (2), checkpoint event (2), endpoint (3)
- ✅ **319 backend tests** (Batch 15): notify_on_error in IRErrorHandler (7)
- ✅ **344 backend tests** (Batch 16): server-side input_vars validation (20) + step-level dry_run guard (5)
- ✅ **362 backend tests** (Batch 18): GET agent endpoint fix + test count reconciliation across 20 test files
- ✅ **388 backend tests** (Batch 20): Trigger automation — 26 tests (cron parsing, HMAC verification, DB models, schemas)
- ✅ **409 backend tests** (Batch 21): Secrets providers — 47 tests (AWS/Azure/Vault/Caching/factory) via mocks
- ✅ **460 backend tests** (Batch 22): Dynamic internal step timeout fix, screenshot_on_fail events, mock_external_calls/test_data_overrides, procedure keyword search, checkpoint retention loop, file_watch trigger loop, GitHub Actions CI
- ✅ **488 backend tests** (Batch 23): Compiler validation hardening (recursive subflow self-reference, template variable enforcement, action/channel compatibility check), agent circuit-breaker dispatch skip, LLM estimated_cost_usd per-run accumulation + per-model cost table, GET /api/projects/{id}/cost-summary endpoint
- ✅ **515 backend tests** (Batch 24): Frontend LLM/agent step detail panel (llm_usage event display, model/token chips, duration_ms pill), approval SLA overdue indicators, backend integration tests (parallel branch, checkpoint resume, approval decision flow, subflow IR); bugfix: execute_llm_action run_service scope
  ✅ **549 backend tests** (Batch 25): estimated_cost_usd on run detail UI; agent dispatch shuffles eligible agents per channel; confirmed mock/test_data_overrides/dry_run/screenshot_on_fail/checkpoint_retention_loop all wired
- ✅ **582 backend tests** (Batch 26): SQLite/PG dual-dialect engine; Alembic setup + `v001_initial_schema` migration; `RunJob` ORM; `cancellation_requested` on `Run`; dialect-aware checkpointer
- ✅ **613 backend tests** (Batch 27): Full durable worker model — `app/worker/` package; `enqueue_run` + `requeue_run`; embedded worker; stall recovery; heartbeat; DB-level cancellation bridge; approval-resume UNIQUE constraint bug fixed
- ✅ **668 backend tests** (Batch 29): HA-safe scheduling — `LeaderElection` class; 18 new tests covering INSERT/renew/steal/lost-election/guard paths

### Remaining gaps
- Backend integration tests are limited (18 API tests) — complex flows like parallel/subflow, checkpoint-retry, approval-resume not tested end-to-end
- No frontend unit or e2e tests
- ~~No CI pipeline (lint + type-check + tests + build gates)~~ → ✅ GitHub Actions CI added (Batch 22)

### Next implementation items
- Add backend integration tests for: parallel branch execution, checkpoint resume, approval decision flow, subflow execution
- Add frontend e2e tests with Playwright for primary operator paths (import procedure, start run, approve, view timeline)

---

## Domain-specific deep roadmap (CKP, workflow, agentic, LLM, UI)

## A) CKP language and compiler evolution
### Why this matters
- CKP is the platform contract; without richer policy semantics, runtime behavior remains hard-coded.

### Next implementation items
- ~~Extend CKP schema with explicit execution policy blocks:~~
  - ~~`retry_policy` (`max_attempts`, `backoff`, `jitter`, `non_retryable_errors`)~~ → ✅ Step-level `retry_config` + global retry policy implemented
  - ~~`timeout_policy` (step/node timeout, fail-open/fail-closed)~~ → ✅ `timeout_ms` enforced at step level + `global_config.timeout_ms` at graph level
  - ~~`idempotency_policy` (custom key template, cache scope)~~ → ✅ Template rendering via Jinja2
- Add CKP-level error handling constructs:
  - ~~`on_error` transition targets~~ → ✅ Error handler dispatch (retry, fail, ignore, escalate, fallback_node)
  - optional compensation/rollback step references
- Strengthen compiler validation:
  - ~~detect unreachable nodes, dead-end branches, recursive subflow loops~~ → ✅ Unreachable nodes (Batch pre-23) + recursive self-reference (Batch 23)
  - ~~enforce required variables for node/step templates~~ → ✅ Jinja2 `{{ var }}` references validated against declared schema (Batch 23)
  - ~~validate action/channel compatibility before runtime~~ → ✅ Sequence steps with non-internal actions require `agent` field (Batch 23)

### Acceptance criteria
- CKP can express retry/timeouts/idempotency without Python code edits
- Invalid policies fail at compile-time with actionable diagnostics

## B) Workflow orchestration maturity
### Why this matters
- Parallel/subflow exists, but operational governance for large workflows is still limited.

### Next implementation items
- Add workflow-level concurrency controls and dedupe windows
- Add subflow contract enforcement:
  - explicit input/output schemas
  - version pinning policy for subflow references
- Add workflow dry-run explain mode:
  - ✅ **[Batch 14]** `POST /api/procedures/{id}/{version}/explain` — static analysis endpoint returns nodes, edges, variables (required/produced/missing), reachable route trace, external calls, policy summary
  - ✅ **[Batch 14]** `explain_service.py` — pure IR analysis; no execution, no DB writes

### Acceptance criteria
- Teams can evolve workflows safely with clear interface contracts
- Operators can predict execution behavior before running in production

## C) Agentic runtime strategy
### Why this matters
- Current model is deterministic execution-first; advanced agentic planning loops are not yet formalized.

### Next implementation items
- Introduce optional planner-executor pattern for selected node types:
  - planner proposes tool/action plan
  - executor applies bounded, policy-checked actions
- Add agent policy guardrails:
  - tool allowlist per procedure/project
  - max tool calls / max iterations / max elapsed time
- Add memory strategy options:
  - per-run ephemeral memory
  - optional project-scoped memory adapter with retention policy

### Acceptance criteria
- Agentic paths remain bounded, auditable, and reproducible under policy
- Planner output and executed actions are visible in run diagnostics

## D) LLM configuration and usage model
### Why this matters
- LLM invocation exists, but enterprise controls (routing, fallback, cost, evaluation) are missing.

### Next implementation items
- Create centralized LLM profile configuration:
  - provider/model routing by task class
  - temperature/token limits/stop sequences
  - fallback model chains on failure/timeout
- Add prompt asset management:
  - versioned prompt templates
  - variable schema checks
  - prompt change audit log
- Add LLM safety + quality controls:
  - output schema validation and repair loop
  - PII redaction pre/post processing
  - policy checks before downstream side effects
- Add LLM cost/performance telemetry:
  - token usage, latency, error rate by model/profile

### Acceptance criteria
- Model selection is policy-driven and observable
- LLM outputs are schema-safe before they affect workflow state

## E) UI roadmap specific to operations and authoring
### Why this matters
- Current UI is strong for run listing/detail, but limited for design-time authoring and deep diagnostics.

### Next implementation items
- Workflow authoring UI phases:
  - read-only graph view
  - editable node properties panel
  - validation hints and compile errors inline
- Run debugger UX:
  - checkpoint timeline viewer
  - retry decision trace
  - idempotency/lease inspection panel
- LLM/agent observability UI:
  - model/profile used per step
  - token/latency stats
  - tool invocation history and outcomes
- Governance UI:
  - ~~approval SLA/escalation indicators~~ → ✅ Done (Batch 24: overdue highlight + ⚠ badge on approvals list + detail)
  - secret usage visibility (without secret value exposure)

### Acceptance criteria
- Operators can debug run failures without direct API/DB calls
- Authors can create and validate CKP workflows from UI with reduced JSON editing

## F) UI technology stack upgrade (recommended)
### Goal
- Move to a scalable, high-velocity frontend architecture for complex operator workflows.

### Recommended stack (best fit for this product)
- Framework/runtime: Next.js App Router + TypeScript (continue)
- Component system: shadcn/ui on top of Radix primitives
- Styling: Tailwind CSS with strict design tokens
- State/data: TanStack Query for server state + Zustand for local UI/workbench state
- Forms/validation: React Hook Form + Zod schemas shared with API contracts
- Data grid: TanStack Table for runs/events/artifact-heavy screens
- Graph editor: React Flow for workflow builder and execution visualization
- Charts/metrics: Recharts for operational dashboards
- Realtime: existing SSE stream retained; optional websocket channel later for collaborative editing
- Testing: Playwright (e2e) + Vitest + React Testing Library
- Quality tooling: ESLint + Prettier + Storybook + Chromatic-style visual regression checks

### UI architecture principles
- Domain-driven frontend modules (`runs`, `procedures`, `approvals`, `workflows`, `settings`)
- Shared typed API client layer with central error mapping and retry policy
- Strong component contracts (presentational vs container separation)
- Accessibility-first primitives (keyboard navigation, focus states, ARIA checks)
- Performance by default (route-level code split, virtualization, optimistic updates where safe)

### Upgrade phases
#### Phase U1 — Foundation
- Introduce design system primitives and page shell standardization
- Add query/state architecture (TanStack Query + Zustand)
- Add form and schema standards (React Hook Form + Zod)

#### Phase U2 — Operations UX
- Rebuild runs and run-detail screens with table virtualization and advanced filtering
- Add timeline grouping/filtering and retry-path overlays
- Add artifact viewer with type-aware preview and download actions

#### Phase U3 — Authoring UX
- Add workflow graph viewer (read-only) using React Flow
- Add editable node inspector with live compile/validation feedback
- Add side-by-side CKP JSON + visual sync mode

#### Phase U4 — Governance and analytics UX
- ~~Add approval SLA and escalation dashboards~~ → ✅ Done (Batch 24: overdue highlight + ⚠ badge)
- ~~Add LLM/agent observability panels (latency, tokens, failures, model profile)~~ → ✅ Done (Batch 24: llm_usage event chips in run timeline)
- Add operator diagnostics views (checkpoint and lease inspection)

### Acceptance criteria
- UI latency remains responsive with large run/event datasets
- Workflow creation and debugging can be completed mostly from UI
- Accessibility and visual consistency pass automated checks

### Migration notes
- Migrate feature-by-feature (strangler pattern), not full rewrite
- Keep existing routes working while incrementally replacing internals
- Define "done" per page: parity, performance, accessibility, and test coverage

---

## Updated delivery phases

## Phase 1 — Runtime diagnostics and retry policy hardening — ✅ COMPLETE
### Deliverables
- ~~Checkpoint/replay diagnostics API~~ → ✅ Done
- ~~Retry policy model (attempt limits + backoff/jitter)~~ → ✅ Done
- ~~Idempotency and lease decision visibility in run diagnostics~~ → ✅ Done

### Acceptance criteria
- Any failed run can be diagnosed from API/UI without direct DB queries
- Retry behavior is deterministic and configurable per step/node

## Phase 2 — Trigger automation ✅ COMPLETE (Batch 20)
### Deliverables
- ~~Scheduler service for CKP scheduled triggers~~ → ✅ APScheduler cron worker + sync loop
- ~~Webhook trigger API with request signing verification~~ → ✅ HMAC-SHA256, 401 on bad sig
- ~~Trigger dedupe/concurrency controls + trigger audit events~~ → ✅ TriggerDedupeRecord + max_concurrent_runs guard

### Acceptance criteria
- ✅ Procedures can execute automatically from schedule/webhook
- ✅ Trigger source and policy decisions are visible in run timeline (trigger_type/triggered_by on Run)

## Phase 3 — Security and governance baseline
### Deliverables
- AuthN/AuthZ and role enforcement
- Secrets provider abstraction + initial adapters
- ~~Redaction policy for events/log payloads~~ → ✅ Done (configurable redaction)

### Acceptance criteria
- ✅ Sensitive values are never exposed in event payloads/UI (redaction active)
- All approval and run actions are attributable to identity (pending AuthN)

## Phase 4 — Observability and operator tooling — ✅ LARGELY COMPLETE
### Deliverables
- ~~Metrics/tracing export~~ → ✅ Prometheus `/api/metrics` + in-memory counters/histograms
- ~~Alert hooks for failed/stuck runs~~ → ✅ `_fire_alert_webhook` on `run_failed`
- ~~Stale lease tooling and replay analyzer endpoint~~ → ✅ Lease admin + diagnostics API

### Acceptance criteria
- ✅ Operators can identify and remediate stuck/failing workflows rapidly
- Remaining: export to external monitoring backend (Prometheus/OTel remote)

## Phase 5 — UX evolution — ✅ LARGELY COMPLETE
### Deliverables
- ~~Rich artifact viewer~~ → ✅ Inline preview + download
- ~~Advanced timeline controls and retry-path visualization~~ → ✅ Retry-with-inputs modal + timeline SSE
- ~~Workflow builder foundation (graph read/edit MVP)~~ → ✅ Visual workflow builder/editor shipped (Batch 33)

### Acceptance criteria
- Operators can debug runs faster with less raw JSON inspection
- Procedure authoring shifts from text-only to assisted visual flow

## Phase 6 — Integrations and scale
### Deliverables
- Expanded agent connector templates and MCP discovery UX
- Production DB/migration hardening
- Background worker model for high-throughput execution

### Acceptance criteria
- Stable operation under higher concurrency and mixed channel load

---

## Production readiness checklist (P0/P1)

This is the minimum set of work to call the system production-ready. Items marked ✅ are already implemented in the repo; everything else is a real deployment blocker.

### P0 — Blockers (must-have)
- **AuthN/AuthZ + roles** (operator/approver/admin)
  - Deliverables: auth middleware, identity propagation, RBAC checks on approvals/runs/admin endpoints
  - Acceptance: every mutating endpoint requires auth; approval decisions restricted to approvers; every run/approval action is attributable to an identity
- **HA-safe triggers + execution** (multi-replica correctness)
  - ✅ **DONE (Batch 29)**: DB-level leader election via `LeaderElection` class (`app/runtime/leader.py`); `SchedulerLeaderLease` row in DB; INSERT-wins / UPDATE-steal / renewal algorithm (TTL 60s, renew 15s); APScheduler sync + `_fire_scheduled_trigger` + `_file_watch_trigger_loop` + `_approval_expiry_loop` all check `leader_election.is_leader` before executing; trigger-service dedupe guard (`TriggerDedupeRecord`) provides belt-and-suspenders protection at the run-creation layer
  - Acceptance: ✅ two orchestrator replicas can run without double-firing schedules or creating duplicate runs
- **Durable worker model** (survive restarts, scale out)
  - ✅ **DONE (Batch 27)**: `app/worker/` package: poll-and-claim loop (`loop.py`), heartbeat/lock renewal (`heartbeat.py`), standalone entrypoint (`worker_main.py`); `enqueue_run` for new runs; `requeue_run` (SELECT-UPDATE-or-INSERT) for approval-resume and retry; SQLite + PostgreSQL claim dialects; embedded worker in server process via `asyncio.create_task`; stalled-job recovery; DB-level `cancellation_requested` flag bridges cancel signal across restarts
  - Remaining: external worker process at scale (run `worker_main.py` separately), horizontal worker scaling, worker count/concurrency tuning docs
- **Production database + migrations**
  - Deliverables: Postgres (or equivalent), Alembic migrations, indexes for hot queries (runs/events/approvals/leases), backup/restore procedure
  - Acceptance: schema upgrades are repeatable and reversible; query latency remains stable under realistic event volumes

### P1 — Hardening (strongly recommended)
- **Observability export** (beyond in-memory)
  - Current: in-memory metrics + Prometheus endpoint exist; export to external backend is still missing
  - Deliverables: OpenTelemetry traces, structured logs with correlation IDs (run_id/node_id/step_id), metrics shipped to managed backend
  - Acceptance: an operator can trace a single run end-to-end across services and agents; alerts can be derived from SLOs
- **Frontend e2e tests (Playwright)**
  - Deliverables: e2e coverage for import procedure → start run → approve → view timeline/artifacts
  - Acceptance: CI gate blocks regressions on core operator paths
- **Load + soak testing**
  - Deliverables: concurrency test plan (parallel runs + heavy event streams + approvals), soak tests for memory growth/leaks
  - Acceptance: defined throughput targets and observed stable behavior (no runaway DB growth, no event-stream stalls)
- **Agent capacity & pool model (true RR/fairness)**
  - Current: eligible agents are shuffled per dispatch to spread load; there is no `pool_id` or fairness/stickiness guarantees
  - Deliverables: explicit pool_id, fair/deterministic selection, capacity-aware routing, saturation signals
  - Acceptance: predictable distribution across agents under load, and clear operator signals when a pool is saturated

---

## Next Sprint (P0): Production baseline plan

Goal: ship the minimum **safe deployment baseline** (security + HA correctness + durable execution + production DB discipline).

1) **AuthN/AuthZ + roles**
- Implement identity (JWT/session) and a small role model: `operator`, `approver`, `admin`
- Enforce RBAC on:
  - approvals decision endpoints (approver/admin only)
  - agent/lease admin endpoints (admin only)
  - run/procedure mutation endpoints (operator/admin)
- Acceptance: unauthenticated requests are rejected; audit fields show who triggered runs/approvals

2) ~~**HA-safe triggers (no double-fire)**~~ ✅ **DONE (Batch 29)**
- DB-level leader election: `LeaderElection` in `app/runtime/leader.py`; `SchedulerLeaderLease` table; INSERT-wins / UPDATE-steal / renewal (TTL 60s, renew 15s)
- APScheduler + file-watch + approval-expiry loops all skip when `leader_election.is_leader` is False
- Belt-and-suspenders: trigger-service dedupe guard (`TriggerDedupeRecord`) prevents duplicate run creation even in edge cases

3) ~~**Durable worker model (API/worker split)**~~ ✅ **DONE (Batch 27)**
- `app/worker/` package: `enqueue_run` (new runs) + `requeue_run` (approval-resume/retry); poll-and-claim loop with SQLite optimistic lock + PostgreSQL `FOR UPDATE SKIP LOCKED`; heartbeat task renews lock + bridges `cancellation_requested` DB flag to in-process `asyncio.Event`; stall recovery requeues jobs with expired locks; embedded in server process; `worker_main.py` for standalone deployment
- Approval decision and retry now use `requeue_run` — fixes prior silent UNIQUE-constraint violation that lost approval decisions

4) ~~**Production DB + migrations**~~ ✅ **DONE (Batch 26)**
- Alembic `v001_initial_schema` migration covers all tables including `run_jobs`; `sync_db_url()` converts async URL to sync for Alembic; PostgreSQL `asyncpg` engine supported; `alembic upgrade head` required before starting with PostgreSQL

5) **Verification / release gates**
- Add at least 1 “smoke” integration test that runs a minimal procedure end-to-end (create → run → events)
- Acceptance: CI remains green; smoke test fails if critical wiring breaks

Non-goals for this sprint (explicitly deferred): multi-tenancy, full external observability backend (OTel traces/log pipelines), autoscaling, advanced pool capacity model.

---

## Testing and quality plan (cross-phase)

- Backend unit tests: compiler, routing, retry, idempotency, lease behavior
- Backend integration tests: parallel/subflow, approval-resume, checkpoint-retry, artifact lifecycle
- Frontend tests: runs/procedures/approvals/artifacts core workflows
- CI gates: lint + type-check + test + build

---

---

## Established patterns and architectural strengths (use these as templates)

### Proven runtime patterns
- **Checkpointer integration**: `execution_service._invoke_graph_with_checkpointer` shows correct LangGraph checkpoint pattern with fallback
- **Step idempotency**: `node_executors._mark_step_started/completed` + cache retrieval demonstrates replay-safe side-effect management
- **Resource leases**: `node_executors._acquire_agent_lease/_release_lease` + `lease_service` provides safe multi-agent concurrency control
- **Retry preparation**: `run_service.prepare_retry` + retry event tracking shows stateful retry entry pattern
- **Artifact extraction**: `_extract_artifacts_from_result` demonstrates extensible result normalization

### Proven API patterns
- **SSE streaming**: `events.py` shows correct async generator pattern for live event streams
- **Filter/pagination**: `runs.py` list_runs with date range + status filtering shows good query design
- **Cleanup operations**: `runs.py` cleanup_runs_before with preview-before-delete pattern is solid
- **Nested resource access**: `/runs/{id}/events`, `/runs/{id}/artifacts` shows clear hierarchy

### Proven UI patterns
- **Live updates**: `runs/[id]/page.tsx` SSE subscription + event deduplication is working well
- **Optimistic state**: Artifact live notice and timeline auto-scroll demonstrate good UX responsiveness
- **Filter presets**: Quick date presets (24h/7d/30d) in runs page show good operator ergonomics

### Data model strengths
- **Event sourcing**: `RunEvent` table with append-only timeline is correct audit pattern
- **Thread-based execution**: `Run.thread_id` for checkpoint context is the right LangGraph integration
- **Step idempotency table**: Composite key (run_id, node_id, step_id) + result caching is solid design
- **Lease expiry**: `ResourceLease.expires_at` + periodic cleanup enables fault-tolerant concurrency

**Use these patterns when implementing new features**: Follow the same async context manager, event emission, and state persistence patterns already established in services and runtime layers.

---

## Critical implementation gaps (CKP spec vs current code)

### Missing CKP top-level fields in parser/IR
**Current state** (as of 2026-02-18 audit): Parser reads `procedure_id`, `version`, `global_config` including `secrets_config` and `audit_config`, `variables_schema`, `workflow_graph`, `provenance`, `retrieval_metadata`.

**Still missing from IR and runtime**:
- `trigger` field (manual/scheduled/webhook/event/file_watch) — not parsed, no DB model, no scheduler/webhook handler
- ~~`retrieval_metadata` (intents, domain, keywords)~~ → ✅ Parsed and stored (Batch 10); tag search supported
- ~~`provenance` (compiled_on, compiler_version, sources)~~ → ✅ Parsed and stored in DB (Batch 10)
- `global_config` deep fields not enforced:
  - `screenshot_on_fail` — parsed but not enforced globally
  - ~~`timeout_ms`~~ → ✅ `asyncio.wait_for` wraps entire graph invocation (Batch 7)
  - ~~`checkpoint_strategy`~~ → ✅ `"none"` strategy disables checkpointer (Batch 11)
  - ~~`checkpoint_retention_days`~~ → ✅ `_checkpoint_retention_loop` background task prunes RunEvent rows for terminal runs (Batch 22)
  - ~~`execution_mode` (dry_run/validation_only)~~ → ✅ dry_run enforced at step level (Batch 16); `validation_only` mode also works (Batch 5)
  - ~~`mock_external_calls`, `test_data_overrides`~~ → ✅ both wired in node_executors: mock returns stub + emits step_mock_applied; overrides return configured result + emits step_test_override_applied (Batch 22/25)
  - ~~`rate_limiting`~~ → ✅ `max_concurrent_operations` (semaphore) + `max_requests_per_minute` (token bucket) enforced (Batches 6 + 8)
- ~~`variables_schema.required[].validation` (regex, max, allowed_values)~~ — ✅ server-side enforcement via `validate_input_vars` in `POST /api/runs` (Batch 16)

**Already fixed (no longer gaps)**:
- ~~`max_retries`, `retry_delay_ms`~~ — ✅ enforced with exponential backoff
- ~~`secrets_config` (provider, vault_url)~~ — ✅ integrated via secrets_service
- ~~`audit_config`~~ — ✅ redaction active
- ~~`variables_schema.*.sensitive` flag~~ — ✅ drives redaction

### Missing node-level policy enforcement
**All resolved**:
- ~~`sla.max_duration_ms` / `on_breach` / `escalation_handler`~~ → ✅ Node-level SLA monitored, `sla_breached` event emitted, escalation/fail dispatched (Batches 5 + 13)
- ~~`telemetry.track_duration`, `track_retries`, `custom_metrics`~~ → ✅ All emitted in step events and recorded (Batches 10 + 11)
- ~~Custom `idempotency_key` templates~~ → ✅ Jinja2 template rendering applied (Batch 7)

### Missing step-level features
**All resolved**:
- ~~Step `timeout_ms` not enforced~~ → ✅ `asyncio.wait_for` wraps all three binding paths: internal, agent_http, mcp_tool (Batch 10)
- ~~`wait_ms` / `wait_after_ms`~~ → ✅ `asyncio.sleep` enforced before/after each step (Batch 10)
- ~~Per-step retry policy override~~ → ✅ Step-level `retry_config` + LLM-node `retry` dict override global policy (Batch 14)

### Missing node type completions
**All resolved**:
- ~~Error handlers (`recovery_steps`, `fallback_node`)~~ → ✅ Fully dispatched: retry, fail, ignore, escalate, screenshot_and_fail, fallback_node (Batches 7 + 15)
- ~~Compensation/rollback steps~~ → ✅ `on_failure` handler routes to recovery node (Batch 6)

### Missing operator/diagnostic APIs
**All resolved**:
- ✅ `GET /api/runs/{run_id}/diagnostics` — implemented with idempotency, lease, retry, event data
- ✅ `GET /api/runs/{run_id}/checkpoints` — implemented with LangGraph saver introspection
- ✅ `GET /api/leases` + `DELETE /api/leases/{id}` — stale lease force-release implemented
- ✅ `POST /api/procedures/{id}/{version}/explain` — dry-run static analysis (Batch 14)

### Missing UI features
**Already implemented**:
- ✅ Workflow graph viewer (React Flow, read-only) with custom CKP nodes, minimap, types
- ✅ Projects, leases, agents pages with full CRUD and in-app `ConfirmDialog` (no browser popups)
- ✅ Diagnostics tab in run detail page
- ✅ Metrics panel on dashboard
- ✅ Input variables form at run-start with constraint validation
- ✅ Retry-with-modified-inputs modal on failed runs
- ✅ Dark mode toggle with localStorage persistence
- ✅ Artifact preview/download
- ✅ Bulk operations on runs list
- ✅ SSE-based live approvals

**Still missing**:
- ~~Visual workflow builder/editor (editable properties, not just read-only)~~ → ✅ Done (Batch 33: `WorkflowBuilder.tsx` — node palette, inspector, round-robin edges, CKP export/import; "Builder ✏" tab on Procedure Version page)
- ~~Frontend: `estimated_cost_usd` cost display on run detail page~~ → ✅ Done (Batch 25: shown in LLM tokens bar alongside prompt/completion/total)

---

## Suggested execution order for next sprints

### Sprint 1: Quick runtime fixes — ✅ ALL DONE
1. ~~Implement `asyncio.sleep(wait_ms)` for the `wait` action~~ → ✅ Batch 10
2. ~~Wrap agent HTTP calls with `asyncio.wait_for(timeout_ms / 1000)` and emit `step_timeout` event~~ → ✅ Batch 10
3. ~~Invoke `IRErrorHandler.recovery_steps` / `fallback_node` in `execute_sequence`~~ → ✅ Batch 7
4. ~~Fix input variables: read procedure `variables_schema` in frontend, prompt at run-start~~ → ✅ Batch 3

### Sprint 2: Frontend UX quick wins — ✅ ALL DONE
1. ~~Add diagnostics tab to run detail page~~ → ✅ Done
2. ~~Add metrics panel to dashboard~~ → ✅ Done
3. ~~Extract shared UI components (`StatusBadge`, `ApprovalStatusBadge`)~~ → ✅ Batch 13
4. ~~Add input variables form modal at run-start~~ → ✅ Batch 3

### Sprint 3: Operator tooling — ✅ ALL DONE
1. ~~Implement SLA monitoring~~ → ✅ Batches 5 + 13
2. ~~Add Prometheus-compatible `/metrics` endpoint~~ → ✅ Batch 13
3. ~~Add alert hooks (configurable webhook) for `run_failed` events~~ → ✅ Batch 13
4. ~~Add dry-run explain mode API for workflow route simulation~~ → ✅ Batch 14

### Sprint 4: Policy enforcement hardening — ✅ ALL DONE
1. ~~Enforce `variables_schema` validation (regex, allowed_values, required) at bind time~~ → ✅ Batch 16
2. ~~Implement `global_config.rate_limiting` at workflow concurrency level~~ → ✅ Batches 6 + 8
3. ~~Add per-node retry policy override support~~ → ✅ Batch 14
4. ~~Respect `global_config.execution_mode` dry_run flag~~ → ✅ Batch 16

### Sprint 5: Trigger automation — ✅ COMPLETE (Batch 20)
1. ~~Add `trigger` field parsing to IR + DB table~~ → ✅ Batch 19/20
2. ~~Implement scheduler worker (cron expression evaluation)~~ → ✅ APScheduler AsyncIOScheduler in runtime/scheduler.py
3. ~~Implement webhook trigger endpoint with request signing verification~~ → ✅ HMAC-SHA256 in POST /api/triggers/webhook/{id}
4. ~~Add trigger audit trail and dedupe window logic~~ → ✅ TriggerDedupeRecord table + check_dedupe() + concurrency guard

### Sprint 6: Security and governance ← ✅ COMPLETE (Batch 32)
1. ✅ **AuthN/AuthZ middleware** — JWT/OIDC `Authorization: Bearer` + `X-API-Key` via `app/auth/deps.py`; `get_current_user` FastAPI dependency; `AUTH_ENABLED=false` (default) means zero-breaking rollout
2. ✅ **Role model** — `admin`, `operator`, `approver`, `viewer`; `require_role()` dependency factory in `app/auth/roles.py`; wired to all mutating endpoints
3. ✅ **Approval RBAC guard** — `POST /api/approvals/{id}/decision` requires `approver` role; `decided_by` set from authenticated `principal.identity` as fallback
4. ✅ **API key support** — `X-API-Key` header grants `operator` role; keys in `settings.API_KEYS`
5. ✅ **Secret rotation cache flush** — `invalidate_secrets_cache()` + `SECRETS_ROTATION_CHECK=true` calls it before each run execution
6. ✅ **Metrics Pushgateway remote export** — `METRICS_PUSH_URL` + `METRICS_PUSH_INTERVAL_SECONDS` background push task
7. ✅ **Agent round-robin** — `pool_id` column on `AgentInstance`; `_find_capable_agent` uses per-pool monotonic counter (v003 migration)
8. ✅ **Metadata search SQL LIKE** — `GET /api/procedures?metadata_search=<query>` adds DB-level LIKE filter on `retrieval_metadata_json`

### Sprint 7: Testing and CI hardening
1. Add backend integration tests for: parallel branch execution, checkpoint resume, approval decision flow, subflow
2. Expand frontend e2e tests beyond core flows (edge/error/retry scenarios)
3. Add GitHub Actions CI pipeline: ruff + pyright + pytest + next build
4. Add backend performance/concurrency tests for lease management

---

## Enterprise Readiness & Futuristic Roadmap

> Added 2026-02-19. This section captures what is needed to move from a strong prototype to a production-grade enterprise platform, plus longer-horizon thinking. Items here supplement the sprint plan above.

---

### Enterprise Gap Assessment

| Domain | Current State | Gap Level |
|---|---|---|
| Identity & Governance (AuthN/AuthZ) | **100% — Batch 32: `AUTH_ENABLED` opt-in; JWT Bearer + X-API-Key; role guards on mutations; `/api/auth/token`** | **COMPLETE** |
| Trigger Automation (cron/webhook/event/file_watch) | 100% — Batch 20 + Batch 22 | COMPLETE |
| **HA-safe Scheduling (Leader Election)** | **100% — Batch 29: `LeaderElection` DB-row lease; all singleton loops leader-gated** | **COMPLETE** |
| **Durable Worker Model** | **100% — Batch 27: RunJob queue, poll/claim/execute, heartbeat, stall recovery, embedded + standalone modes** | **COMPLETE** |
| **Production DB + Migrations (Alembic)** | **85% — Batch 26: Alembic + v001 migration + PostgreSQL asyncpg; indexes and backup/restore docs still needed** | **LOW** |
| **CI/CD Pipeline** | **100% — Batch 22: GitHub Actions (ruff + pytest + tsc + next build)** | **COMPLETE** |
| Multi-tenancy | 0% — single tenant DB | HIGH |
| **LLM Cost Visibility** | **100% — Batch 23: token tracking + estimated_cost_usd + project cost-summary API; Batch 25: run detail UI** | **COMPLETE** |
| Agent Pool / Circuit Breaker | **100% — Batch 32: `pool_id` + v003 migration; per-pool round-robin counter replaces random shuffle; circuit breaker wired (Batch 23)** | **COMPLETE** |
| Procedure Environment Promotion | no dev→staging→prod path | HIGH |
| Frontend E2E Tests | 35% — Batch 30: 26 Playwright tests across navigation/procedures/runs/approvals | MEDIUM |
| **AWS/Azure Secrets Adapters** | **100% — Batch 21: AWS Secrets Manager (boto3) + Azure Key Vault (DefaultAzureCredential) fully implemented** | **COMPLETE** |
| PII Masking before external LLM calls | not present | MEDIUM |
| Data Residency / Compliance Labels | not present | MEDIUM |
| Approval RBAC governance | **100% — Batch 32: `require_role("approver")` on decision endpoint; `decided_by` auto-set from JWT identity** | **COMPLETE** |
| Secret Rotation Detection | **100% — Batch 32: `SECRETS_ROTATION_CHECK` flushes `CachingSecretsProvider` before each run; `invalidate_secrets_cache()` helper** | **COMPLETE** |
| Workflow Canary / Blue-Green | not present | MEDIUM |

---

## G) Identity, Governance & Security (Sprint 6 expansion)

### Why this matters
The first question any enterprise buyer asks: "who can do what, and can you prove it?"

### Implementation items
- **JWT/OIDC middleware** on all 35+ endpoints — verify bearer token, decode claims, store principal in request state
- **Role model**: `admin` (full), `operator` (start/cancel runs, read all), `approver` (submit approval decisions only), `viewer` (read-only)
- **Per-project scoping**: roles are granted at project level — `operator` on Project A cannot touch Project B
- **Approval RBAC**: `POST /api/approvals/{id}/decision` must verify caller has `approver` role for that procedure's project
- **API Key management**: service accounts for agents to authenticate back to the orchestrator — not just open HTTP
- **Secret rotation detection**: vault integration should watch for TTL expiry and re-fetch; invalidate cached secret mid-run with `secret_rotated` event
- **Full audit attribution**: every run, approval, deletion, and agent registration records the principal identity — not just timestamp
- **Secret rotation + cache invalidation**: detect TTL/rotation and refresh provider caches without restart

### Acceptance criteria
- No endpoint is accessible without a valid identity token
- Approval decisions are attributable to a named identity with role proof
- Secret values never appear in any event, log, or API response

---

## H) Trigger Automation — Full Model (Sprint 5 expansion)

### Why this matters
Manual-only execution blocks real automation. CKP already defines the trigger contract — the runtime just doesn't honour it.

### Implementation items
- **`trigger` field IR model**: parse `manual | scheduled | webhook | event | file_watch` into `IRTrigger` dataclass
- **DB table `trigger_registrations`**: stores active trigger configs per procedure version
- **Cron scheduler worker**: background `asyncio` task evaluating APScheduler jobs; emits `trigger_fired` event; creates run with `triggered_by: schedule`
- **Webhook trigger endpoint**: `POST /api/triggers/webhook/{procedure_id}` — HMAC-SHA256 signature verification, configurable dedupe window (reject duplicate payload hash within N seconds), creates run with `triggered_by: webhook`
- **Event bus trigger**: subscribe to Kafka/SQS topic; on matching message schema create a run — connector pluggable via `trigger.event.source`
- **File watch trigger**: poll S3/blob path for object creation/modification; configurable polling interval
- **Trigger cascade**: emit `run_completed` with output vars; downstream procedures with `trigger.type: event` and matching `event.source: run_completed` auto-fire
- **Trigger audit trail**: every run records `trigger_type`, `trigger_id`, `triggered_by`, `trigger_payload_hash`
- **Trigger dedupe window**: configurable `dedupe_window_seconds` — second webhook with same payload hash within window returns 409 + existing `run_id`
- **Trigger concurrency policy**: `max_concurrent_triggered_runs` per procedure — queue or drop on overflow

### Acceptance criteria
- A procedure with a valid cron expression fires automatically without any manual API call
- Duplicate webhook delivery does not create a duplicate run
- Every triggered run's origin is visible in the run timeline

---

## I) Multi-tenancy

### Why this matters
Required for any SaaS model or internal platform team serving multiple business units.

### Implementation items
- **Tenant model**: `tenant_id` column on `procedures`, `runs`, `agent_instances`, `projects`, `approvals`, `run_events`, `artifacts`
- **Tenant middleware**: extract `tenant_id` from JWT claims; inject into all DB queries as implicit filter
- **Per-tenant resource limits**: `max_concurrent_runs`, `max_procedures`, `max_agents` — stored in `tenant_config` table
- **Cross-tenant subflow**: explicit trust grant model — Tenant A can invoke Tenant B's procedure only with a signed cross-tenant token
- **Tenant-scoped secrets**: vault path prefix is `/{tenant_id}/` — tenants cannot read each other's secrets
- **Tenant usage reporting**: `GET /api/admin/tenants/{id}/usage` — runs, tokens, agent-hours per billing period

---

## J) LLM Cost Visibility & Budget Controls

### Why this matters
LLM costs scale non-linearly. Without token tracking, a runaway loop node can generate a surprise bill within hours.

### Implementation items
- ~~**Token counter per step**: `llm_action` node executor captures `usage.prompt_tokens`, `usage.completion_tokens` from model response; emits `llm_usage` event~~ → ✅ Done (token accumulation in `execute_llm_action`)
- ~~**Run-level cost accumulation**: `runs` table adds `total_prompt_tokens`, `total_completion_tokens`, `estimated_cost_usd` columns; updated at each `llm_usage` event~~ → ✅ Done (Batch 23: `estimated_cost_usd` column + `_MODEL_COST_PER_1K` rates table)
- ~~**Project-level cost rollup**: `GET /api/projects/{id}/cost-summary` — daily/weekly/monthly breakdown~~ → ✅ Done (Batch 23: service + API endpoint with `period_days` param)
- **Budget guardrail in CKP**: `global_config.llm_budget.max_tokens_per_run` — abort run and emit `budget_exceeded` event before limit is reached (warn at 80%, abort at 100%)
- ~~**Model cost config**: central `models.json` stores cost-per-1k-tokens per model~~ → ✅ Done (Batch 23: `_MODEL_COST_PER_1K` dict in `node_executors.py`)
- **Model routing by cost tier**: CKP `llm_action.fallback_model` — on retry, use cheaper model; on first attempt, use full model
- **Cost dashboard widget**: add to frontend dashboard — top 5 most expensive runs this week, cost by project

### Acceptance criteria
- Every LLM-using run has a token count and estimated cost in its detail page
- A procedure with `max_tokens_per_run: 10000` stops execution and surfaces a clear error when that limit is hit

---

## K) Agent Pool, Circuit Breaker & Capacity Model

### Why this matters
A single offline agent silently stalls all runs dispatching to that channel. Production needs resilience.

### Implementation items
- **Agent pool model**: multiple agents can share a `channel` + `pool_id`; dispatcher round-robins across healthy pool members
  - ✅ Partial (Batch 25): channel-based pool selection now shuffles eligible agents to spread load
  - Remaining: `pool_id` field, deterministic/fair round-robin, capacity-aware selection, and stickiness
- ~~**Circuit breaker per agent**: after N consecutive 5xx responses, mark agent status `circuit_open`; stop dispatching; emit `circuit_opened` event; auto-retry after `reset_timeout_seconds`~~ → ✅ Done (Batch 23: `consecutive_failures` + `circuit_open_at` on `AgentInstance`; `_find_capable_agent` skips circuit-open agents; health loop manages open/reset cycle)
- **Health check depth**: beyond `GET /health` — orchestrator sends a no-op probe action and validates response schema
- **Warm/cold states**: `warm` (agent pre-running, ready), `cold` (needs boot); orchestrator can signal `warm_up` before a scheduled trigger fires
- **Agent capability versioning**: agent reports `capabilities_version: "2.1"`; CKP step can pin `required_capability_version: ">=2.0"`; compile-time binding enforces this
- **Pool capacity autoscale hint**: when all pool members are at `max_concurrent_leases`, emit `pool_saturated` event; external autoscaler can react
- **Agent self-healing**: orchestrator sends `restart` signal to agent if it supports `/restart` endpoint; records `agent_restarted` event

---

## L) Procedure Environment Promotion & Safe Delivery

### Why this matters
Right now there is no safe path from a new procedure version in dev to production. One bad import can go live immediately.

### Implementation items
- **Environment labels**: procedures have `environment: dev | staging | production`; runs in `production` env require status `active`
- **Promotion workflow**: `POST /api/procedures/{id}/{version}/promote` — moves from dev→staging or staging→production; requires `admin` role; triggers static analysis (explain) as pre-check
- **Approval gate between stages**: configurable `require_approval_for_promotion: true` in project settings — creates an approval record that blocks promotion until signed off
- **Canary rollout**: `POST /api/procedures/{id}/canary` — `{canary_version, canary_percentage: 10}` — dispatcher sends 10% of triggered runs to new version; metrics compared before full cutover
- **Blue/green swap**: atomic version swap with instant rollback: `POST /api/procedures/{id}/swap-active` with rollback via `POST /api/procedures/{id}/rollback`
- **Impact analysis before promotion**: resolve all subflow references from the new version; find all procedures that `import` this procedure; surface list with version constraints

---

## M) Data Compliance & PII Controls

### Why this matters
For healthcare, finance, legal — sending raw user data to an external LLM is a compliance violation.

### Implementation items
- **PII detection layer**: before any `llm_action` step, run a configurable PII scanner (regex + NER model) on input variables marked `sensitivity: high`
- **PII tokenization**: replace detected PII with reversible tokens (`<PII_EMAIL_1>`) before sending to LLM; detokenize on response
- **Data classification on artifacts**: `artifact.classification: confidential | restricted | internal | public`; download endpoint enforces classification-based access control
- **GDPR deletion**: `DELETE /api/runs/{id}/personal-data` — scrubs event payloads, artifact content, and input_vars for a run without deleting the audit shell
- **Compliance policy-as-code**: top-level CKP field `compliance.frameworks: ["SOC2", "HIPAA"]` — compiler checks node actions against a policy registry and rejects prohibited combinations at import time
- **Audit export**: `GET /api/audit/export?from=&to=&format=CEF` — structured compliance log export for SIEM ingestion

---

## N) Futuristic Capabilities (2–3 Year Horizon)

### N1. Self-Authoring / Observer-to-Automation (O2A)
The biggest paradigm shift deferred but highest long-term value:
- Screen-level observation (desktop/web) → infer step types, actions, selectors
- Generate CKP skeleton from observed trace → validate at compile time → human review and annotation
- Dry-run the generated procedure → diff produced trace vs expected → auto-fix discrepancies
- Makes LangOrch a **recorder + replayer**, not just an executor
- Unlocks non-developer authors — business analysts can automate by demonstration

### N2. AI Planner Node (Bounded Agentic Loop)
A `planner` node type where the CKP declares a **goal + guardrails**, not pre-written steps:
```json
{
  "type": "planner",
  "objective": "Enrich the product listing with missing attributes",
  "tools_allowed": ["web_search", "extract_text", "database_query"],
  "max_iterations": 10,
  "policy": { "tool_call_audit": true, "budget_tokens": 4000 }
}
```
- Orchestrator runs a bounded ReAct/Plan-and-Execute loop inside the node
- Every tool call is still a step event — fully auditable, fully replayable
- `max_iterations` + `budget_tokens` keep it bounded and cost-predictable

### N3. Procedure Marketplace / Registry
- Procedures as versioned, publishable artifacts — like npm for workflows
- `@acme/invoice-processing@1.2.0` published and importable by other teams
- Dependency graph: procedure A `requires` procedure B (subflow) at `>=1.1.0`
- Signing + provenance verification before import (publisher identity, attestation chain)
- Public/private registry modes; enterprise-gated marketplace

### N4. Temporal Reasoning in Workflows
- **Time-conditional branches**: `if today is last_business_day_of_month → go to reconciliation_node`
- **Business-hours-aware SLA clock**: SLA timeout counts only during configured business hours for a given timezone/calendar
- **Deadline propagation**: parent approval `due_in: 4h` → child escalation fires at `3h45m` automatically
- **Scheduled continuations**: run pauses mid-execution; resumes at a declared future time without holding a thread

### N5. Collaborative Live Workflow Editing
- Multiple authors editing the same CKP simultaneously — cursor presence, last-write-wins merge or conflict detection
- `diff before save` with impact analysis: "your change removes node X which is referenced by 2 other procedures"
- Structural changes to `active` procedures require `approver` sign-off before deployment (edit gate)
- Field-level comments and review threads — GitHub PR review model applied to workflow authoring

### N6. Execution Intelligence & Anomaly Detection
- Orchestrator learns "normal" for a procedure over N runs:
  - Step X typically takes 800ms — today it took 12s → auto-alert
  - Agent Y returns empty results >20% of the time → flag for review
- **Auto-remediation suggestions**: "this node failed the same way 8 times in 7 days — consider adding a retry or fault handler"
- **Predicted completion time**: based on historical duration distribution, surfaces ETA with confidence interval on run detail page
- **Cost anomaly detection**: this run is on track to spend 3× the average cost — warn operator mid-run

### N7. Declarative Compliance Policies (Policy-as-Code)
For regulated industries — enforce at compile time, not audit time:
```json
{
  "compliance": {
    "frameworks": ["SOC2", "HIPAA"],
    "prohibitions": ["export_pii_to_external_llm", "store_unencrypted_phi"],
    "required_approvers": { "data_classification": "restricted", "min_approvers": 2 },
    "audit_exports": { "destination": "s3://compliance-bucket", "format": "CEF" }
  }
}
```
- Compiler checks CKP against policy registry at import time
- Rejects procedures that violate declared compliance constraints before they can ever run
- Policy violations surfaced as compile errors with actionable fix hints

### N8. Federated Multi-Orchestrator Mesh
- Multiple LangOrch instances (per region, per business unit) forming a mesh
- A run started in Region A can dispatch subflows to Region B while respecting data residency constraints
- Central control plane (policy + identity) with distributed execution planes
- Cross-orchestrator event correlation and unified audit trail

---

## Prioritised Next-Sprint Picks (post-Batch 29)

Ordered by enterprise value vs implementation cost:

| Priority | Item | Estimated Effort | Unblocks |
|---|---|---|---|
| P0 | Trigger automation (cron + webhook) | 2 sprints | ✅ Done (Batch 20) |
| P0 | AuthN/AuthZ + role model | 2 sprints | Multi-user deployment |
| P0 | Durable worker model | Large | ✅ Done (Batch 27) |
| P0 | Production DB + migrations | ✅ Done (Batch 26) | Alembic + PostgreSQL |
| P0 | HA-safe scheduling (leader election) | Small | ✅ Done (Batch 29) |
| P1 | CI/CD pipeline (GitHub Actions) | 0.5 sprint | ✅ Done (Batch 22) |
| P1 | Frontend e2e tests (Playwright) | 1 sprint | Enterprise buyer checklist |
| P1 | LLM token tracking + cost dashboard | 1 sprint | ✅ Done (Batch 23) |
| P1 | `{{run_id}}` template variables + run-scoped artifacts | Small | ✅ Done (Batch 28) |
| P1 | Artifact retention/cleanup (TTL + background sweep) | Small | Prevents unbounded disk growth |
| P2 | Agent circuit breaker + pool model | 1 sprint | ✅ Circuit breaker done (Batch 23); ✅ load distribution via shuffle done (Batch 25); pool_id + fair RR remaining |
| P2 | Procedure environment promotion | 1 sprint | Safe delivery pipeline |
| P2 | AWS/Azure secrets adapters | 0.5 sprint | ✅ Done (Batch 21) |
| P3 | Multi-tenancy scoping | 3 sprints | SaaS / platform model |
| P3 | PII detection + tokenization before LLM | 1.5 sprints | HIPAA / GDPR compliance |
| P4 | Visual workflow builder (edit mode) | 3 sprints | Non-developer authoring |
| P4 | AI Planner node type | 2 sprints | Advanced agentic capability |
| P5 | O2A self-authoring (record + replay) | 4+ sprints | Platform differentiation |
