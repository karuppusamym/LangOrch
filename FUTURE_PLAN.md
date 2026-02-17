# LangOrch Future Plan (Code-Aligned)

Last updated: 2026-02-16

This roadmap is updated from direct code analysis of current backend, runtime, API, and frontend implementation.

---

## Current implementation baseline (what is already done)

## Strongly implemented
- CKP compile pipeline (parse → validate → bind) and runtime execution graph
- Runtime executors for `sequence`, `logic`, `loop`, `parallel`, `subflow`, `processing`, `verification`, `llm_action`, `human_approval`, `transform`, `terminate`
- Checkpoint-enabled invocation with SQLite checkpointer and thread-based context
- Step idempotency persistence + cached replay path
- Agent dispatch with resource lease acquisition/release
- Retry preparation flow and retry fallback resume from `last_node_id`
- Run event timeline + SSE stream + step/subflow/artifact events
- Artifact extraction/persistence + artifacts API + basic frontend rendering
- Core CRUD APIs for procedures, runs, approvals, and agents

## Partially implemented
- Secrets handling exists in runtime state, but no external secret provider integration
- Telemetry field exists in state, but no metrics/export pipeline
- Approval flow exists, but no role-based approver governance
- Artifact support exists, but metadata normalization/retention controls are limited

## Not yet implemented (high impact gaps)
- Trigger automation (scheduler, webhook, file/event driven execution)
- AuthN/AuthZ and policy enforcement
- Checkpoint introspection and replay diagnostics APIs/UI
- Retry policy controls (max attempts, backoff/jitter, per-node policy)
- Operator tooling (stale lease management, incident diagnostics)
- Automated test suites + CI gates
- Visual workflow builder and advanced run-debug UX

---

## Gap analysis by domain

## 1) Execution correctness and recoverability
### Current
- Durable graph execution and retry resume foundations are in place.

### Gaps
- No first-class API/UI for checkpoint introspection by `run_id`/`thread_id`
- Retry behavior is not policy-driven yet (per-node retry configs are missing)
- Idempotency diagnostics are not exposed in operator-friendly APIs

### Implementation next
- Add `GET /api/runs/{run_id}/diagnostics` including:
  - last node/step
  - retry markers
  - idempotency decisions
  - lease state snapshot
- Add configurable retry policy model in CKP/runtime binding

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
### Current
- Basic platform operation without identity enforcement.

### Gaps
- No platform AuthN/AuthZ
- No secrets provider abstraction
- No redaction policy for sensitive run payloads/events

### Implementation next
- Add auth middleware and role model (`operator`, `approver`, `admin`)
- Add secrets resolver abstraction (env + pluggable vault adapters)
- Add event/log redaction pipeline with field policy map

## 4) Observability and operations
### Current
- Timeline events and run status APIs exist.

### Gaps
- No structured metrics, tracing, alerting hooks, or operator diagnostics console

### Implementation next
- Add metrics export (`run_duration`, `run_failures`, `approval_wait_time`)
- Add run diagnostics endpoint and failure classification
- Add lease operations API (list stale leases, force release with audit trail)

## 5) Frontend operations UX
### Current
- Runs, procedures, approvals, and artifacts have baseline pages.

### Gaps
- No visual workflow authoring, limited timeline filtering/grouping, limited artifact UX.

### Implementation next
- Add timeline filters and retry-path rendering
- Add richer artifact panel (preview/download/group by node/step)
- Start workflow builder foundation with read-only graph visualization first

## 6) Quality and delivery discipline
### Current
- Ad-hoc validation and manual smoke flows are present.

### Gaps
- No committed automated backend/frontend test suites and no CI quality gates.

### Implementation next
- Add backend unit + integration tests for runtime edge cases
- Add frontend smoke/e2e tests for primary operator paths
- Add CI pipeline for lint + test + build

---

## Domain-specific deep roadmap (CKP, workflow, agentic, LLM, UI)

## A) CKP language and compiler evolution
### Why this matters
- CKP is the platform contract; without richer policy semantics, runtime behavior remains hard-coded.

### Next implementation items
- Extend CKP schema with explicit execution policy blocks:
  - `retry_policy` (`max_attempts`, `backoff`, `jitter`, `non_retryable_errors`)
  - `timeout_policy` (step/node timeout, fail-open/fail-closed)
  - `idempotency_policy` (custom key template, cache scope)
- Add CKP-level error handling constructs:
  - `on_error` transition targets
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
  - route simulation
  - variable dependency report
  - side-effect risk flags

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

## Phase 1 — Runtime diagnostics and retry policy hardening (immediate)
### Deliverables
- Checkpoint/replay diagnostics API
- Retry policy model (attempt limits + backoff/jitter)
- Idempotency and lease decision visibility in run diagnostics

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
- Redaction policy for events/log payloads

### Acceptance criteria
- Sensitive values are never exposed in event payloads/UI
- All approval and run actions are attributable to identity

## Phase 4 — Observability and operator tooling
### Deliverables
- Metrics/tracing export
- Alert hooks for failed/stuck runs
- Stale lease tooling and replay analyzer endpoint

### Acceptance criteria
- Operators can identify and remediate stuck/failing workflows rapidly
- SLO-grade operational metrics are available

## Phase 5 — UX evolution
### Deliverables
- Rich artifact viewer
- Advanced timeline controls and retry-path visualization
- Workflow builder foundation (graph read/edit MVP)

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
**Current state**: Parser reads only `procedure_id`, `version`, `global_config` (shallow), `variables_schema` (shallow), `workflow_graph`.

**Missing from IR and runtime**:
- `trigger` field (manual/scheduled/webhook/event/file_watch) — not parsed, no DB model, no scheduler/webhook handler
- `retrieval_metadata` (intents, domain, keywords) — not stored, no search/discovery API
- `provenance` (compiled_on, compiler_version, sources) — not captured in IR or DB
- `global_config` deep fields not enforced:
  - `screenshot_on_fail`, `max_retries`, `retry_delay_ms`, `timeout_ms` are not enforced globally
  - `checkpoint_strategy`, `checkpoint_retention_days` not implemented
  - `execution_mode` (dry_run/validation_only) not respected
  - `mock_external_calls`, `test_data_overrides` not wired
  - `rate_limiting` not enforced at workflow or platform level
  - `secrets_config` (provider, vault_url) not integrated
  - `audit_config` (storage, retention, include_sensitive_data) not implemented
- `variables_schema.required[].validation` (regex, max, allowed_values, sensitive flag) — parsed but not enforced in runtime variable binding

### Missing node-level policy enforcement
**Current state**: Nodes parse `sla`, `telemetry`, `idempotency_key` but do not enforce them.

**Missing behavior**:
- `sla.max_duration_ms` / `on_breach` / `escalation_handler` not monitored or enforced
- `telemetry.track_duration`, `track_retries`, `custom_metrics` fields exist but metrics not exported
- `idempotency_key` is stored per step but not used for custom key templates from CKP policy

### Missing step-level features
**Current state**: Steps execute action dispatch + idempotency + retry-on-failure.

**Missing**:
- Step-level retry policies (`llm_action.retry.max_retries`, `delay_ms`) not deeply enforced
- Step timeout not enforced independently from global timeout
- `validation` fields in steps not checked before execution

### Missing node type completions
**Current state**: All node types are implemented at runtime.

**Gaps in error/compensation flow**:
- Error handlers with `recovery_steps` parsed but not executed
- `on_error` transition targets not added to graph wiring
- Compensation/rollback steps mentioned in CKP spec but no runtime implementation

### Missing operator/diagnostic APIs
**Current state**: Basic run/event timeline exists.

**Missing**:
- No `GET /api/runs/{run_id}/diagnostics` (idempotency/lease/retry/checkpoint state snapshot)
- No `GET /api/runs/{run_id}/checkpoints` (checkpoint timeline introspection)
- No `GET /api/leases` or force-release stale lease tooling
- No dry-run explain mode API for workflow route simulation

### Missing UI features vs spec
**Current state**: Runs/procedures/approvals pages exist with basic timeline + artifact rendering.

**Missing**:
- No workflow graph viewer (read-only or editable)
- No retry-path visualization in timeline
- No step-by-step debugger with variable inspection
- No LLM/agent invocation detail panel (model used, tokens, latency)
- No approval SLA/escalation indicators
- No operator diagnostics console

---

## Suggested execution order for immediate next sprints

### Sprint 1: CKP spec completion + diagnostics foundation
1. Add missing IR fields (`trigger`, `retrieval_metadata`, `provenance`)
2. Extend parser to capture trigger + provenance + deep global_config
3. Add run diagnostics API (`GET /api/runs/{run_id}/diagnostics`)
4. Add checkpoint introspection API (`GET /api/runs/{run_id}/checkpoints`)

### Sprint 2: Policy enforcement (retry + timeout + SLA)
1. Implement configurable retry policy model (max_attempts, backoff, jitter)
2. Implement node-level SLA monitoring and breach actions
3. Implement step-level timeout enforcement
4. Implement global rate limiting (workflow concurrency + requests/min)

### Sprint 3: Trigger automation
1. Add trigger model + DB table
2. Implement scheduler worker (cron expression evaluation)
3. Implement webhook trigger endpoint with signature verification
4. Add trigger audit trail and dedupe window logic

### Sprint 4: Security and governance
1. Implement secrets resolver abstraction + provider adapters (env, vault)
2. Implement event/payload redaction policy
3. Add AuthN/AuthZ middleware + role model
4. Add audit trail enrichment with identity + sensitive flag handling

### Sprint 5: Observability and operator tools
1. Implement metrics export (OpenTelemetry or Prometheus-compatible)
2. Add lease operations API (list stale leases, force release)
3. Add alert hooks for failed/stuck runs
4. Add dry-run explain mode API

### Sprint 6: Frontend UX upgrades
1. Add workflow graph viewer (React Flow, read-only first)
2. Add retry-path visualization in timeline
3. Add LLM/agent observability panel
4. Add diagnostics console page

### Sprint 7: Testing and CI hardening
1. Add backend unit tests (compiler validation, retry logic, idempotency)
2. Add backend integration tests (parallel/subflow, checkpoint recovery)
3. Add frontend e2e tests (Playwright for runs/procedures/approvals flows)
4. Add CI pipeline (lint + type-check + tests + build gates)
