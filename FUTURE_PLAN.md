# LangOrch Future Plan (Code-Aligned)

Last updated: 2026-02-19 (updated after Batch 18 cleanup + Enterprise Readiness & Futuristic Roadmap analysis added)

This roadmap is updated from direct code analysis of current backend, runtime, API, and frontend implementation.

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
- Artifact extraction/persistence + artifacts API + frontend rendering
- Core CRUD APIs for procedures, runs, approvals, agents, projects, and leases — 35+ endpoints total
- **Projects API**: full CRUD (`GET/POST/PUT/DELETE /api/projects`), project filter on procedure list
- **Agent management**: register, update (status/capabilities), delete agents; background health polling every 60 s
- **Leases API**: `GET /api/leases` + `DELETE /api/leases/{id}` — stale lease force-release implemented
- **Diagnostics API**: `GET /api/runs/{id}/diagnostics` — idempotency entries, active leases, event counts, retry markers
- **Checkpoint introspection API**: `GET /api/runs/{id}/checkpoints` + `GET /api/runs/{id}/checkpoints/{cpid}`
- **Secrets provider abstraction**: `EnvironmentSecretsProvider` (working) + `VaultSecretsProvider` (working), AWS/Azure stubs
- **Event redaction**: recursive sensitive field sanitization (password, token, api_key, secret, etc.)
- **In-memory metrics**: counters/histograms + `GET /api/runs/metrics/summary` endpoint
- **Graph extraction API**: `GET /api/procedures/{id}/{version}/graph` → React Flow-compatible nodes/edges
- **Workflow graph viewer (frontend)**: interactive React Flow with custom CKP nodes, color-coding, minimap, zoom/pan
- **362 backend tests** across 20 test files — all passing (parser, validator, binder, redaction, metrics, secrets, graph, API, batches 7–16)
- 12-route frontend: Dashboard, Procedures (list/detail/edit/version-diff), Runs (list/detail/timeline/bulk-ops), Approvals (inbox/detail/SSE-live), Agents, Projects, Leases
- **Dark mode**: system-preference-aware toggle in header, persisted to localStorage
- **Retry with modified inputs**: run detail retry button opens variables editor pre-filled with original inputs
- **Procedure version diff**: side-by-side CKP JSON diff viewer with line-level LCS comparison
- **Artifact preview**: inline text/JSON preview + download button for all artifacts
- **Bulk operations**: multi-select checkboxes on runs list with bulk cancel/delete + confirmation
- **SSE for approvals**: real-time approval push via `GET /api/approvals/stream` (replaces 10s polling)
- **Configurable redaction**: `build_patterns()` merges CKP `audit_config.redacted_fields` with default patterns

### Partially implemented
- Secrets handling: env/vault working; AWS Secrets Manager and Azure Key Vault are stubs with env fallback
- Telemetry fields: `track_duration` and `track_retries` emitted in step events; `custom_metrics` recorded; not exported to external backends
- Approval flow exists, but no role-based approver governance
- ~~Error handlers fully parsed into IR but NOT executed at runtime~~ → ✅ Fully dispatched (Batches 7 + 15)
- ~~`wait`/`wait_after_ms` stored in steps but the `wait` action is a no-op placeholder~~ → ✅ `asyncio.sleep` enforced (Batch 10)
- ~~`idempotency_key` custom templates stored but not evaluated~~ → ✅ Jinja2 template rendering applied (Batch 7)

### Not yet implemented (high impact gaps)
- Trigger automation (scheduler, webhook, file/event driven execution) — `trigger` field not parsed
- AuthN/AuthZ and policy enforcement
- ~~Step/node timeout enforcement~~ → ✅ `asyncio.wait_for` wraps agent_http, mcp_tool, and internal steps (Batch 10)
- ~~SLA monitoring~~ → ✅ `sla.max_duration_ms` tracked, `sla_breached` events emitted, escalation/fail enforced (Batches 5 + 13)
- ~~Stale lease management~~ → ✅ `GET/DELETE /api/leases` endpoints + frontend /leases page implemented
- ~~Rate limiting~~ → ✅ `max_concurrent_operations` (semaphore) + `max_requests_per_minute` (token bucket) enforced (Batches 6 + 8)
- ~~Frontend: no diagnostics/metrics pages, no input variables form~~ → ✅ All implemented (diagnostics tab, metrics panel, input vars form)
- Artifact metadata normalization/retention controls are limited
- Visual workflow builder/editor (read-only viewer exists)
- Automated frontend tests + CI gates

---

## Gap analysis by domain

## 1) Execution correctness and recoverability
### Current — UPDATED 2026-02-18
- ✅ Durable graph execution with LangGraph SQLite checkpointer
- ✅ `GET /api/runs/{id}/diagnostics` — idempotency entries, active leases, event counts, retry markers
- ✅ `GET /api/runs/{id}/checkpoints` — full checkpoint introspection
- ✅ Retry with exponential backoff (max_retries, delay_ms, backoff_multiplier) enforced globally

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
### Current
- Runs are manually started through API/UI.

### Gaps
- No scheduler, webhook trigger endpoint, signature verification, or dedupe window.

### Implementation next
- Add trigger registry + run policy controls
- Add cron scheduler worker and signed webhook entrypoint
- Emit explicit trigger-origin events (`triggered_by`, `trigger_type`, `trigger_id`)

## 3) Security and governance
### Current — UPDATED 2026-02-17
- ✅ Secrets provider abstraction: `EnvironmentSecretsProvider` (prefix-based, working) + `VaultSecretsProvider` (hvac, KV v1/v2, working)
- ✅ Event redaction: recursive sensitive field sanitization active in all event emission paths
- AWS Secrets Manager and Azure Key Vault are provider stubs (fall back to env with warning)

### Remaining gaps
- No platform AuthN/AuthZ — all 26 endpoints are open
- No role-based approval governance (any caller can submit approval decisions)
- ~~Redaction policy is hardcoded key-name patterns~~ — ✅ Configurable via `build_patterns(extra_fields)` + `emit_event(extra_redacted_fields=...)`

### Next implementation items
- Add auth middleware and role model (`operator`, `approver`, `admin`)
- Implement AWS Secrets Manager and Azure Key Vault provider adapters
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
- ~~Track node execution start time vs `sla.max_duration_ms`, emit `sla_breached` event~~ → ✅ Done (Batch 13)
- ~~Add Prometheus-compatible `/metrics` endpoint using existing in-memory MetricsCollector~~ → ✅ Done (Batch 13)
- ~~Add alert hooks (configurable webhook or log-based) for `run_failed` and stuck runs~~ → ✅ Done (Batch 13)
- Export metrics to external Prometheus/OpenTelemetry backend (currently in-memory only)

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
- No LLM/agent invocation detail panel (model used, tokens, latency)
- No approval SLA/escalation indicators
- ~~Duplicate UI components: `StatusBadge` defined independently~~ — ✅ Extracted to `src/components/shared/`

### Next implementation items
- ~~Add diagnostics tab to run detail page using existing `GET /api/runs/{id}/diagnostics`~~ — ✅ Done
- ~~Add metrics card to dashboard using `GET /api/runs/metrics/summary`~~ — ✅ Done
- ~~Add input variables form modal at run-start that reads `variables_schema` from the procedure~~ — ✅ Done
- ~~Extract `StatusBadge` and `ApprovalStatusBadge` into `src/components/shared/`~~ — ✅ Done
- Add LLM/agent step detail panel (model, tokens, latency)
- Add approval SLA/escalation indicators

## 6) Quality and delivery discipline
### Current — UPDATED 2026-02-18 (Batch 18)
- ✅ 278 backend tests (Batch 13): retry config, step_timeout events, SLA breach, alert webhook, Prometheus, shared UI
- ✅ **312 backend tests** (Batch 14): explain service (19), step retry config (5), LLM retry (3), is_checkpoint marker (2), checkpoint event (2), endpoint (3)
- ✅ **319 backend tests** (Batch 15): notify_on_error in IRErrorHandler (7)
- ✅ **344 backend tests** (Batch 16): server-side input_vars validation (20) + step-level dry_run guard (5)
- ✅ **362 backend tests** (Batch 18): GET agent endpoint fix + test count reconciliation across 20 test files

### Remaining gaps
- Backend integration tests are limited (18 API tests) — complex flows like parallel/subflow, checkpoint-retry, approval-resume not tested end-to-end
- No frontend unit or e2e tests
- No CI pipeline (lint + type-check + tests + build gates)

### Next implementation items
- Add backend integration tests for: parallel branch execution, checkpoint resume, approval decision flow, subflow execution
- Add frontend e2e tests with Playwright for primary operator paths (import procedure, start run, approve, view timeline)
- Add GitHub Actions CI pipeline: `ruff` + `pyright` + `pytest` + `next build`

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
  - detect unreachable nodes, dead-end branches, recursive subflow loops
  - enforce required variables for node/step templates
  - validate action/channel compatibility before runtime

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
  - approval SLA/escalation indicators
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
- Add approval SLA and escalation dashboards
- Add LLM/agent observability panels (latency, tokens, failures, model profile)
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

## Phase 2 — Trigger automation
### Deliverables
- Scheduler service for CKP scheduled triggers
- Webhook trigger API with request signing verification
- Trigger dedupe/concurrency controls + trigger audit events

### Acceptance criteria
- Procedures can execute automatically from schedule/webhook
- Trigger source and policy decisions are visible in run timeline

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
- Workflow builder foundation (graph read/edit MVP) — read-only done, editable pending

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
  - `checkpoint_retention_days` — not implemented
  - ~~`execution_mode` (dry_run/validation_only)~~ → ✅ dry_run enforced at step level (Batch 16); `validation_only` mode also works (Batch 5)
  - `mock_external_calls`, `test_data_overrides` — not wired
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
- LLM/agent invocation detail panel (model, tokens, latency)
- Approval SLA/escalation indicators
- Visual workflow builder/editor (editable properties, not just read-only)

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

### Sprint 5: Trigger automation
1. Add `trigger` field parsing to IR + DB table
2. Implement scheduler worker (cron expression evaluation)
3. Implement webhook trigger endpoint with request signing verification
4. Add trigger audit trail and dedupe window logic

### Sprint 6: Security and governance
1. Add AuthN/AuthZ middleware + role model (`operator`, `approver`, `admin`)
2. Implement AWS Secrets Manager and Azure Key Vault provider adapters
3. ~~Make redaction field list configurable from `global_config.audit_config`~~ → ✅ Batch 17
4. Add role-based check on approval decision submission

### Sprint 7: Testing and CI hardening
1. Add backend integration tests for: parallel branch execution, checkpoint resume, approval decision flow, subflow
2. Add frontend e2e tests with Playwright for primary operator paths
3. Add GitHub Actions CI pipeline: ruff + pyright + pytest + next build
4. Add backend performance/concurrency tests for lease management

---

## Enterprise Readiness & Futuristic Roadmap

> Added 2026-02-19. This section captures what is needed to move from a strong prototype to a production-grade enterprise platform, plus longer-horizon thinking. Items here supplement the sprint plan above.

---

### Enterprise Gap Assessment

| Domain | Current State | Gap Level |
|---|---|---|
| Identity & Governance (AuthN/AuthZ) | 0% — all endpoints open | CRITICAL |
| Trigger Automation (cron/webhook/event) | 0% — manual only | CRITICAL |
| Multi-tenancy | 0% — single tenant DB | HIGH |
| LLM Cost Visibility | 0% — no token tracking | HIGH |
| Agent Pool / Circuit Breaker | single-agent only | HIGH |
| Procedure Environment Promotion | no dev→staging→prod path | HIGH |
| CI/CD Pipeline | 0% — no gates | HIGH |
| Frontend E2E Tests | 0% | HIGH |
| AWS/Azure Secrets Adapters | stub only | MEDIUM |
| PII Masking before external LLM calls | not present | MEDIUM |
| Data Residency / Compliance Labels | not present | MEDIUM |
| Approval RBAC governance | any caller can approve | MEDIUM |
| Secret Rotation Detection | reads once, no invalidation | MEDIUM |
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
- **AWS Secrets Manager adapter**: implement `AWSSecretsProvider` (boto3 `get_secret_value`), replace env fallback
- **Azure Key Vault adapter**: implement `AzureKeyVaultProvider` (azure-keyvault-secrets), replace env fallback

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
- **Token counter per step**: `llm_action` node executor captures `usage.prompt_tokens`, `usage.completion_tokens` from model response; emits `llm_usage` event
- **Run-level cost accumulation**: `runs` table adds `total_prompt_tokens`, `total_completion_tokens`, `estimated_cost_usd` columns; updated at each `llm_usage` event
- **Project-level cost rollup**: `GET /api/projects/{id}/cost-summary` — daily/weekly/monthly breakdown
- **Budget guardrail in CKP**: `global_config.llm_budget.max_tokens_per_run` — abort run and emit `budget_exceeded` event before limit is reached (warn at 80%, abort at 100%)
- **Model cost config**: central `models.json` stores cost-per-1k-tokens per model; used for `estimated_cost_usd` calculation
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
- **Circuit breaker per agent**: after N consecutive 5xx responses, mark agent status `circuit_open`; stop dispatching; emit `circuit_opened` event; auto-retry after `reset_timeout_seconds`
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

## Prioritised Next-Sprint Picks (post-Batch 18)

Ordered by enterprise value vs implementation cost:

| Priority | Item | Estimated Effort | Unblocks |
|---|---|---|---|
| P0 | Trigger automation (cron + webhook) | 2 sprints | Real automation |
| P0 | AuthN/AuthZ + role model | 2 sprints | Multi-user deployment |
| P1 | CI/CD pipeline (GitHub Actions) | 0.5 sprint | Enterprise buyer checklist |
| P1 | Frontend e2e tests (Playwright) | 1 sprint | Enterprise buyer checklist |
| P1 | LLM token tracking + cost dashboard | 1 sprint | Production cost safety |
| P2 | Agent circuit breaker + pool model | 1 sprint | Production resilience |
| P2 | Procedure environment promotion | 1 sprint | Safe delivery pipeline |
| P2 | AWS/Azure secrets adapters | 0.5 sprint | Secrets audit compliance |
| P3 | Multi-tenancy scoping | 3 sprints | SaaS / platform model |
| P3 | PII detection + tokenization before LLM | 1.5 sprints | HIPAA / GDPR compliance |
| P4 | Visual workflow builder (edit mode) | 3 sprints | Non-developer authoring |
| P4 | AI Planner node type | 2 sprints | Advanced agentic capability |
| P5 | O2A self-authoring (record + replay) | 4+ sprints | Platform differentiation |
