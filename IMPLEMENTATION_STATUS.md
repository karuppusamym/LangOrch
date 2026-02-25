# LangOrch Implementation Status

Last updated: 2026-02-24 (Batch 37: 9-Issue Sprint Completion —
**P0** `frontend/src/components/WorkflowBuilder.tsx`: Fixed visual builder typing bug and moved Config to DB;
**P1** `backend/app/services/validator.py`: Added variable name cross-validation, default CKP generation, and Apigee integration;
**P2** `backend/app/api/agent_credentials.py` & `backend/app/api/agents.py`: Implemented encrypted credential assets, secure agent credential pull model (JWT grants), and agent bootstrap/heartbeats;
**P3** `backend/app/api/auth.py` & `frontend/src/app/login/page.tsx`: Completed Azure AD / LDAP / OIDC User Management with auto-provisioning)

This document is the single authoritative source for **what is implemented vs what is missing**, derived from direct code analysis of all backend and frontend source files.

---

## Canonical remaining gaps (single source of truth)

Use this section as the authoritative snapshot of what is still missing. If any later section conflicts with this list, this list wins.

| Gap | Current state | Priority |
|-----|---------------|----------|
| External observability backend | Prometheus endpoint + Pushgateway push are implemented; Prometheus text label format now correct; full OpenTelemetry traces/log shipping/correlation backend is pending | P0 |
| Event-bus trigger adapters | Cron/webhook/file-watch/manual are implemented; Kafka/SQS-style consumer adapters are pending | P1 |
| Multi-tenant isolation | Single-tenant model; no tenant-scoped data partitioning and policy enforcement | P1 |
| Procedure promotion/canary/rollback | Versioning + status lifecycle (`PATCH /status`) done; controlled environment promotion and canary/blue-green rollout are pending | P1 |
| LLM routing & gateway | Dynamic per-call LLM client, externalised cost table, circuit breaker on LLM + MCP all implemented (Batch 35); cost-based fallback model selection policy is pending | P1 |
| API gateway integration | `LLM_GATEWAY_HEADERS` supports static header injection (Batch 35); full dynamic Apigee/Kong integration (rate-limiting, token exchange) is pending | P2 |
| Compliance controls | No PII tokenization pre-LLM, GDPR erase flow, or policy-as-code compile checks | P2 |
| Agent pool capacity signals | `pool_id` + deterministic round-robin exist; saturation/autoscale signals and capability-version policy are pending | P2 |
| Test hardening breadth | Strong unit coverage + core Playwright flows; broader load/soak and failure-path e2e coverage are pending | P2 |

---

## Real-World Hybrid Workflow Examples

These three examples demonstrate how LangOrch's three-tier node model (Deterministic 🔵 / Intelligent 🟣 / Control 🟠) maps to complete end-to-end business processes. Each workflow is fully expressible as a CKP procedure today using the existing 11 node types.

---

### 1. Invoice Processing — OCR → Validation → AI Anomaly Detection → Approval → ERP Update

**Business context:** A scanned or emailed invoice arrives as an image or PDF. The system must extract structured data, validate it against purchase order records, detect any anomalies or fraud signals, route for human approval when thresholds require it, and write the approved record to the ERP.

**Why hybrid:** OCR and ERP writes are deterministic API calls. Anomaly detection requires reasoning over patterns that cannot be expressed as simple rules (unusual vendor, inconsistent line items, currency mismatches) — this is where the LLM adds value. Approval is an explicit governance gate.

```
[sequence: ingest_document]          🔵  POST to OCR service; store raw text + metadata as artifact
         │
[llm_action: extract_fields]         🟣  Extract vendor, amount, line items, PO number from raw OCR text
         │                               Structured output schema enforces required fields
[verification: validate_schema]      🟠  Assert all required fields present and amount parseable
         │               │
      (pass)          (fail)
         │               └─[sequence: flag_extraction_error] → [terminate: failed]
[sequence: fetch_po_record]          🔵  GET purchase order from ERP by PO number
         │
[llm_action: anomaly_detection]      🟣  Compare invoice vs PO — flag vendor mismatch, amount variance,
         │                               unusual payment terms, duplicate invoice signals
         │                               Output: { risk_score: float, flags: string[], recommendation: string }
[verification: check_risk_output]    🟠  Validate risk_score is numeric and in 0–1 range
         │
[logic: route_by_risk]               🟠  risk_score > 0.6 → human review; <= 0.6 → auto-approve path
         │                    │
   (high risk)           (low risk)
         │                    └─[sequence: auto_approve_log] → [sequence: update_erp] → [terminate: success]
[human_approval: manager_review]     🟠  Show flags + recommendation to approver; 48h timeout
         │               │               on_timeout → escalate path
      (approve)       (reject)
         │               └─[sequence: notify_rejection] → [terminate: rejected]
[sequence: update_erp]               🔵  POST approved invoice to ERP system; idempotency_key prevents duplicates
         │
[sequence: archive_document]        🔵  Move artifact to long-term storage, update document status
         │
[terminate: success]                 🟠
```

**Node-by-node rationale:**

| Step | Tier | Reason |
|------|------|--------|
| `ingest_document` | 🔵 Deterministic | OCR is a well-defined API call with deterministic output given same input |
| `extract_fields` | 🟣 Intelligent | Raw OCR output is noisy, unstructured; LLM handles layout variance across vendor formats |
| `validate_schema` | 🟠 Control | Structural check on model output before it drives downstream steps |
| `fetch_po_record` | 🔵 Deterministic | Exact-match database lookup — no ambiguity |
| `anomaly_detection` | 🟣 Intelligent | Cross-referencing invoice vs PO for semantic inconsistency requires judgment, not rules |
| `route_by_risk` | 🟠 Control | Implements the business policy: risk threshold routing |
| `manager_review` | 🟠 Control | Explicit governance gate — human decision recorded in audit trail |
| `update_erp` | 🔵 Deterministic | Write to authoritative system of record — must be reliable and idempotent |

**Key CKP fields used:**
- `idempotency_key` on `update_erp` — prevents double-posting if the run retries after ERP write
- `is_checkpoint: true` on `manager_review` — durable resume after human decision
- `timeout_ms` on `manager_review` — auto-escalate if no response within SLA
- `global_config.max_cost_usd` — caps combined spend from two LLM nodes per run
- `artifact` output from `ingest_document` — OCR result stored and referenced by subsequent nodes

---

### 2. Customer Support — Data Fetch → AI Classification → Conditional Routing → Response Generation

**Business context:** An inbound support ticket arrives (email, chat, or API). The system fetches the customer's account history and open cases, classifies the inquiry type and urgency, routes to the appropriate handling path (auto-response, specialist queue, or escalation), and generates a personalised response.

**Why hybrid:** Data fetching is deterministic. Classification and response generation require natural language understanding — rules cannot handle the semantic variety of real customer messages. Routing is pure control logic once classification produces a structured output.

```
[sequence: fetch_ticket]             🔵  Pull ticket content, customer_id, channel metadata
         │
[parallel: enrich_context]           🟠  Fan-out two deterministic lookups simultaneously
    │               │
[sequence:          [sequence:       🔵  GET /customers/{id}/account  |  GET /customers/{id}/cases
 fetch_account]      fetch_cases]         Both results merged into shared state
    │               │
    └───────┬────────┘
            │
[llm_action: classify_inquiry]       🟣  Classify: category (billing / technical / account / feedback),
            │                            urgency (low / medium / high / critical),
            │                            sentiment (positive / neutral / negative / frustrated)
            │                            Output: structured JSON with all three dimensions
[verification: validate_classification] 🟠  Check category and urgency are valid enum values
            │
[logic: routing_decision]            🟠  critical → immediate_escalation
            │                            high + technical → specialist_queue
            │                            billing → billing_team
            │                            low/medium → auto_response path
            │
    ┌───────┼──────────────┐
    │       │              │
[sequence: [sequence:     [llm_action:  🟣  Generate personalised reply grounded in
 escalate]  queue_ticket]  auto_reply]       account history, case context, and inquiry
    │       │              │                  type. Tone matched to detected sentiment.
    │       │              │
    │       │       [verification:     🟠  Check reply does not contain PII patterns,
    │       │        check_reply]           forbidden phrases, or empty content
    │       │              │
    └───────┴──────────────┘
            │
[sequence: send_response]            🔵  POST reply via channel API (email/chat/SMS)
            │
[sequence: update_ticket_status]     🔵  PATCH ticket: status, assigned_team, classification tags
            │
[terminate: success]                 🟠
```

**Node-by-node rationale:**

| Step | Tier | Reason |
|------|------|--------|
| `fetch_ticket` | 🔵 Deterministic | Structured API read — ID-keyed, no ambiguity |
| `enrich_context` (parallel) | 🟠 Control | Orchestrates concurrent data fetching; no logic, just fan-out |
| `fetch_account` / `fetch_cases` | 🔵 Deterministic | Database/API reads with deterministic output |
| `classify_inquiry` | 🟣 Intelligent | Natural language messages cannot be classified by keyword rules with acceptable accuracy |
| `validate_classification` | 🟠 Control | Catches model output that is not a valid enum before it drives routing |
| `routing_decision` | 🟠 Control | Pure business policy: classification value → handling path |
| `auto_reply` | 🟣 Intelligent | Personalised reply generation requires context-aware language; templates would be too rigid |
| `check_reply` | 🟠 Control | Quality gate: ensures generated reply meets content policy before sending |
| `send_response` | 🔵 Deterministic | Channel API call — deterministic, idempotency-key prevents duplicate send |
| `update_ticket_status` | 🔵 Deterministic | Structured write to support system |

**Key CKP fields used:**
- `parallel.branches` on `enrich_context` — concurrent account and case fetches with shared join
- `logic.rules` array on `routing_decision` — ordered condition list, first match wins
- `is_checkpoint: true` on `classify_inquiry` — replay-safe resume; classification not re-run on retry
- `agent` on `auto_reply` — routes to a specific LLM-capable agent in the pool
- `verification.schema` on `validate_classification` and `check_reply` — JSON Schema constraints

---

### 3. Contract Review — Extraction → Multi-Agent Analysis → Parallel Approvals → Signing

**Business context:** A contract document (PDF, DOCX) must be reviewed for legal compliance, commercial terms acceptability, and security/data obligations before being offered for signature. Multiple specialist reviewers (legal, commercial, security) assess in parallel. All must approve before the document proceeds to e-signature.

**Why hybrid:** Extraction and document handling are deterministic. Each specialist review requires semantic reasoning over legal and technical language — this is the highest-value use of LLMs. The parallel approval structure encodes the organisational governance model.

```
[sequence: ingest_contract]          🔵  Fetch document, extract text via document parser API,
         │                               store original + extracted text as named artifacts
[llm_action: extract_metadata]       🟣  Extract: parties, effective date, jurisdiction, contract type,
         │                               key obligation clauses, termination conditions, governing law
         │                               Output: structured contract_metadata object
[verification: validate_metadata]    🟠  Assert required parties, date, and jurisdiction fields present
         │
[parallel: specialist_analysis]      🟠  Fan-out to three independent analysis paths simultaneously
    │               │               │
[llm_action:   [llm_action:    [llm_action:    🟣  Each agent has a specialist system prompt and
 legal_review]  commercial_    security_             focused scope:
                review]        review]         legal: compliance, liability, IP clauses
                                               commercial: payment, SLA, penalty terms
                                               security: data residency, retention, breach obligation
    │               │               │
[verification: [verification: [verification:  🟠  Validate each output is structured risk assessment
 check_legal]   check_comm]    check_sec]           { risk_level, findings: [], recommendation }
    │               │               │
    └───────────────┼───────────────┘
                    │
[llm_action: synthesis_report]       🟣  Consolidate three specialist reports into executive summary:
                    │                    overall_risk, blocking_issues, negotiation_points, recommendation
[transform: prepare_approval_pack]   🔵  Reshape synthesis + metadata into approval request payload
                    │
[parallel: approval_gates]           🟠  All three approvals must be obtained (fan-out + join)
    │               │               │        Each gate runs independently; any rejection blocks the join
[human_approval: [human_approval: [human_approval: 🟠  legal_counsel | commercial_dir | security_officer
 legal_sign_off]  commercial_ok]  security_ok]         Each: on_approve → continue; on_reject → reject_path
    │               │               │
    └───────────────┼───────────────┘
                    │
[logic: all_approved?]               🟠  Check join: if any branch produced rejection, route to revise
         │               │
    (all pass)      (any reject)
         │               └─[llm_action: revision_brief] → [sequence: notify_requester] → [terminate: rejected]
[sequence: send_to_esign]            🔵  POST to e-signature platform (DocuSign/Adobe Sign)
         │
[sequence: update_contract_registry] 🔵  PATCH contract record: status=awaiting_signature, approval_ids
         │
[terminate: success]                 🟠
```

**Node-by-node rationale:**

| Step | Tier | Reason |
|------|------|--------|
| `ingest_contract` | 🔵 Deterministic | Document parsing API — deterministic given same input |
| `extract_metadata` | 🟣 Intelligent | Legal clause extraction requires language understanding; field locations vary by contract template |
| `specialist_analysis` (parallel) | 🟠 Control | Orchestrates concurrent expert analysis; no intelligence in the parallel node itself |
| `legal_review` / `commercial_review` / `security_review` | 🟣 Intelligent | Each is a focused LLM with specialist system prompt — operates in its domain only |
| `check_legal` / `check_comm` / `check_sec` | 🟠 Control | Structural validation of each model output before it feeds the synthesis |
| `synthesis_report` | 🟣 Intelligent | Cross-domain consolidation: legal + commercial + security risks require holistic reasoning |
| `prepare_approval_pack` | 🔵 Deterministic | Pure state reshape — no I/O, no reasoning |
| `approval_gates` (parallel) | 🟠 Control | Encodes the governance policy: *all three domains must approve* |
| `legal_sign_off` / `commercial_ok` / `security_ok` | 🟠 Control | Explicit human decision boundary with full audit trail per approver |
| `revision_brief` | 🟣 Intelligent | If rejected, LLM generates structured revision guidance from the combined rejection reasons |
| `send_to_esign` | 🔵 Deterministic | Reliable API call to e-signature platform; idempotency_key prevents duplicate submission |

**Key CKP fields used:**
- `parallel.branches` (nested twice) — concurrent analysis and concurrent approvals are separate parallel nodes; inner branches can independently fail
- `is_checkpoint: true` on each `human_approval` — each approval gate is a durable resume point; the procedure survives server restarts between approvals
- `subflow` could replace the `specialist_analysis` parallel block if each specialist analysis becomes complex enough to warrant its own versioned procedure
- `agent` field on each `llm_action` — routes each specialist review to a pool with an appropriate model (e.g. legal review to a model fine-tuned on legal text)
- `global_config.max_cost_usd` — contracts with many LLM nodes need a budget ceiling; four LLM calls per contract can accumulate significant token spend
- `artifacts` — original document, extracted text, and synthesis report all stored as named artifacts for the audit trail

---

### Cross-cutting patterns visible in all three workflows

| Pattern | Invoice | Support | Contract |
|---------|---------|---------|----------|
| **Deterministic bookend** | Fetch doc at start, write ERP at end | Fetch ticket at start, update ticket at end | Fetch doc at start, send to e-sign at end |
| **Intelligent core** | Extract fields + anomaly detection | Classify + generate reply | Extract + multi-specialist analysis + synthesis |
| **Verification gate after every LLM** | ✅ After both LLM nodes | ✅ After classification and reply | ✅ After each of four LLM nodes |
| **Human approval as governance layer** | Manager approval above threshold | Specialist for high-urgency tickets | Three-party parallel approval |
| **Parallel for concurrency** | — | Account + case lookup | Specialist analysis + approval gates |
| **Cost control** | `max_cost_usd` on 2 LLM nodes | `max_cost_usd` on 2 LLM nodes | `max_cost_usd` on 4 LLM nodes |
| **Durable checkpoints** | At human approval gate | At classification (expensive to re-run) | At each of three approval gates |

---

## Summary scorecard

| Domain | Spec Coverage | Implementation | Status |
|--------|---------------|----------------|---------|
| CKP compiler (parse → validate → bind) | 100% | 98% | Complete — step retry_config field added |
| CKP top-level fields (trigger, provenance) | 100% | 100% | trigger: parsed → stored → TriggerRegistration DB → scheduler/webhook wired; provenance parsed+stored |
| All 11 node type executors | 100% | 100% | Complete |
| Global config enforcement | 100% | 95% | timeout, on_failure, rate_limit, execution_mode, vars_schema, checkpoint_strategy all enforced |
| Policy: retry/backoff (global) | 100% | 100% | Complete |
| Policy: retry/backoff (per-step) | 100% | 100% | Step-level retry_config overrides global |
| Policy: retry/backoff (per-node llm_action) | 100% | 100% | payload.retry dict overrides global for LLM nodes |
| Policy: timeout/SLA (global) | 100% | 100% | asyncio.wait_for wraps full graph stream |
| Policy: timeout/SLA (step-level) | 100% | 100% | Agent+MCP+internal steps (both fast-path and dynamic-resolve) wrapped with asyncio.wait_for (Batch 22) |
| Policy: rate limiting | 100% | 80% | max_concurrent_operations + max_requests_per_minute both enforced |
| Trigger automation | 100% | 100% | TriggerRegistration DB + service + APScheduler cron worker + webhook endpoint (HMAC, dedupe, concurrency guard) + frontend Trigger tab; file_watch background poll loop wired (Batch 22) |
| Checkpointing + replay | 100% | 100% | checkpoint_strategy="none" supported; is_checkpoint per-node forcing; checkpoint_saved event emitted |
| Step idempotency | 100% | 95% | Template key evaluation implemented |
| Multi-agent concurrency (leases) | 100% | 95% | Near-complete |
| Human-in-the-loop | 100% | 100% | Approval expiry auto-timeout implemented |
| Secrets provider (env + Vault + AWS + Azure) | 100% | 100% | All 4 providers complete + `provider_from_config()` factory; **Batch 33**: `execution_service.py` wiring fixed — AWS/Azure providers now actually used (were silently falling back to env vars); Vault now passes full AppRole/KV config |
| Observability (events + SSE) | 100% | 98% | checkpoint_saved event added |
| Observability (in-memory metrics) | 100% | 100% | Prometheus `/api/metrics` text endpoint + Pushgateway remote export + p95 histogram; **Batch 33**: Prometheus label format fixed — proper `{key="value"}` syntax, one `# TYPE` per family |
| Observability (telemetry fields) | 100% | 90% | track_duration+track_retries emitted; custom_metrics recorded; Pushgateway export configurable |
| Redaction | 100% | 100% | Configurable via build_patterns() + extra_redacted_fields |
| Diagnostics API | 100% | 100% | Complete |
| Checkpoint introspection API | 100% | 100% | Complete |
| Graph extraction API | 100% | 100% | Complete |
| Dry-run explain API | 100% | 100% | POST /{id}/{version}/explain — static analysis, no execution |
| Procedure status lifecycle API | 100% | 100% | **Batch 33**: `PATCH /api/procedures/{id}/{version}/status` added — lightweight `draft`→`active`→`deprecated`→`archived` transitions without re-uploading full CKP JSON |
| LLM budget governance | 100% | 80% | **Batch 33**: hard budget abort implemented (`global_config.max_cost_usd` → `budget_exceeded` event + run failure); cost tracking + event emission already existed; fallback-model routing policy is still pending |
| Projects CRUD | 100% | 100% | Complete — backend + frontend |
| Agent capabilities + health polling | 100% | 100% | Complete — capabilities in UI, health loop polls /health, circuit breaker (threshold=3, reset=300s) |
| Agent management (update/delete) | 100% | 100% | PUT/DELETE endpoints + frontend buttons |
| Agent pool round-robin dispatch | 100% | 100% | `pool_id` column + v003 migration; deterministic per-pool round-robin replaces random shuffle; **Batch 34**: `GET /api/agents/pools` endpoint — per-pool agent count, status breakdown, concurrency, active leases, available capacity, circuit-open count |
| Frontend: core CRUD pages (12 routes) | 100% | 100% | Complete |
| Frontend: projects page | 100% | 100% | Complete — list/create/edit/delete |
| Frontend: workflow graph viewer | 100% | 95% | Implemented |
| Frontend: dark mode | 100% | 100% | ThemeProvider + header toggle + localStorage |
| Frontend: retry with modified inputs | 100% | 100% | Modal with variables editor on failed runs |
| Frontend: procedure version diff | 100% | 100% | LCS line-level side-by-side diff viewer |
| Frontend: artifact preview/download | 100% | 100% | Inline text/JSON preview + download button |
| Frontend: bulk operations on runs | 100% | 100% | Multi-select + bulk cancel/delete |
| Frontend: SSE approvals | 100% | 100% | Real-time push via EventSource |
| Frontend: diagnostics/metrics pages | 100% | 100% | Complete |
| Frontend: input variables form | 100% | 100% | Complete — constraint validation in UI |
| Frontend: toast notification system | 100% | 100% | Complete |
| Frontend: leases admin page | 100% | 100% | Complete |
| Frontend: status/filter/metadata display | 100% | 100% | Complete |
| Frontend: agent capabilities display | 100% | 100% | Complete |
| Frontend: project filter in procedures | 100% | 100% | Complete |
| Frontend: workflow builder/editor | 100% | 100% | Visual drag-and-drop builder (WorkflowBuilder.tsx): node palette, inspector, edge labels, export to CKP — Builder ✏ tab on Procedure Version page; **Batch 34**: 3-tier node categories (Deterministic/Intelligent/Control), category-consistent color scheme, grouped palette sections with color headers, category badge on node cards, 3 workflow templates (Invoice Processing, Customer Support, Contract Review) |
| Queue visibility API | 100% | 100% | **Batch 34**: `GET /api/queue` — depth by status, total pending/running/done/failed, next 20 pending jobs with priority + available_at |
| Artifact metadata | 100% | 100% | **Batch 34**: `name` / `mime_type` / `size_bytes` columns added to `artifacts` table, `ArtifactOut` schema, `create_artifact()` signature; SQLite idempotent migrations wired |
| Frontend→Backend API linkage | 100% | 100% | All 35+ call sites verified; 204-body bug fixed |
| Backend tests (unit) | Target | 99% | **681 tests** — all passing (Batch 34 confirmed) |
| Backend tests (integration) | Target | 35% | 18 API tests |
| Frontend tests | Target | 35% | 26 Playwright e2e tests (navigation, procedures, runs, approvals) — **Batch 30** |
| AuthN/AuthZ | Target | 85% | Implemented as opt-in (`AUTH_ENABLED`) with JWT + API key + role guards on mutating endpoints; remaining work is production-default enablement, OIDC integration, and project-scoped RBAC |
| Production DB + migrations (Alembic) | Target | 85% | Alembic setup complete; `v001_initial_schema` migration (includes `run_jobs`); SQLite/PostgreSQL dual-dialect; asyncpg engine pool; Alembic env.py; `sync_db_url()` (Batch 26) |
| Durable worker model (RunJob queue) | Target | 100% | Full worker: `app/worker/` package — `loop.py` (poll/claim/execute/stall-reclaim), `heartbeat.py` (lock renewal + cancel bridge), `worker_main.py` (standalone entrypoint), `enqueue_run` + `requeue_run`; embedded in server via `asyncio.create_task`; SQLite + PostgreSQL claim dialects; DB-level run cancellation (Batch 27) |
| CI/CD pipeline | Target | 100% | GitHub Actions CI: backend ruff + pytest; frontend tsc + build (Batch 22) |

---

## What is fully implemented (confirmed by code audit)

### CKP Compiler pipeline (backend/app/compiler/)
- parser.py: all 11 node types, all step fields, error_handlers, SLA, telemetry, idempotency_key
- validator.py: procedure_id, version, start_node, dangling node references for all node types, multi-error collection
- binder.py: compile-time action binding (internal vs external)
- ir.py: 20 dataclasses covering all CKP constructs

### Runtime execution engine (backend/app/runtime/)
- All 11 node executors (node_executors.py, ~1495 lines): sequence, logic, loop, parallel, processing, verification, llm_action, human_approval, transform, subflow, terminate
- LangGraph StateGraph construction with conditional routing (logic/approval/loop)
- Checkpoint-aware execution with LangGraph SQLite saver and resume from last_node_id
- Step idempotency (check then execute then store in step_idempotency table)
- Retry with exponential backoff per step (max_retries, delay_ms, backoff_multiplier)
- Dynamic agent dispatch from agent_instances DB at runtime
- Resource lease acquisition/release with TTL and concurrency_limit enforcement
- Human-in-the-loop: pause, create approval DB record, interrupt, resume after decision
- Parallel branch execution with wait_strategy (all/any) and branch_failure policy
- Subflow execution: child procedure compile, nested graph, input/output variable mapping
- Transform operations: filter, map, aggregate (count/sum/min/max), sort, unique
- Template engine: path.to.var expansion, dotted paths, defaults, recursive dict/list; `_build_template_vars()` injects `{{run_id}}` and `{{procedure_id}}` as built-in variables — available in every step param without declaring in `variables_schema`
- Safe expression evaluator: 12 operators, no eval(), boolean/number coercion

### Services (backend/app/services/) - 9 services
- execution_service.py: full pipeline: compile, validate, bind, load secrets, build graph, checkpoint-invoke, persist artifacts, update metrics
- secrets_service.py: EnvironmentSecretsProvider, VaultSecretsProvider (token + AppRole, KV v1/v2, namespace), AWSSecretsManagerProvider (boto3, JSON field extraction, LocalStack endpoint, paginated list), AzureKeyVaultProvider (DefaultAzureCredential, underscore→hyphen normalisation), CachingSecretsProvider (TTL decorator), provider_from_config factory
- checkpoint_service.py: introspection via LangGraph SQLite saver - list checkpoints, get checkpoint state
- graph_service.py: BFS traversal to React Flow nodes + edges, layout, color coding, node labels
- lease_service.py: try_acquire, release, list_active, concurrency enforcement
- run_service.py, procedure_service.py, approval_service.py, event_service.py: CRUD + lifecycle

### Connectors (backend/app/connectors/)
- agent_client.py: HTTP POST /execute + GET /health protocol
- llm_client.py: OpenAI-compatible chat completions
- mcp_client.py: MCP tool protocol POST /tools/{name} + GET /tools

### Utilities (backend/app/utils/)
- metrics.py: in-memory counters + histograms, record_run_started/completed/retry, get_metrics_summary
- redaction.py: recursive field sanitization by key pattern (password, token, api_key, secret, credential, authorization)

### Database (backend/app/db/) - 11 tables
projects, procedures, runs, run_events, approvals, step_idempotency, artifacts, agent_instances, resource_leases, run_jobs, trigger_registrations

- `run_jobs` — durable execution queue: `job_id`, `run_id` (UNIQUE), `status` (queued/running/done/failed/retrying/cancelled), `priority`, `attempts`, `max_attempts`, `locked_by`, `locked_until`, `available_at`, `error_message`
- `trigger_registrations` — persistent trigger config per procedure version (Batch 20)

### API layer - 38 endpoints confirmed

| Endpoint | Status |
|----------|--------|
| GET /api/health | Complete |
| GET /api/metrics | Complete — Prometheus text exposition format |
| POST/GET /api/procedures | Complete |
| GET /api/procedures/{id}/versions | Complete |
| GET/PUT/DELETE /api/procedures/{id}/{version} | Complete |
| GET /api/procedures/{id}/{version}/graph | Complete |
| POST /api/procedures/{id}/{version}/explain | Complete — dry-run static analysis, no execution |
| POST/GET /api/runs | Complete |
| GET /api/runs/metrics/summary | Complete |
| GET /api/runs/{id} | Complete |
| GET /api/runs/{id}/artifacts | Complete |
| GET /api/runs/{id}/diagnostics | Complete |
| GET /api/runs/{id}/checkpoints | Complete |
| GET /api/runs/{id}/checkpoints/{cpid} | Complete |
| POST /api/runs/{id}/cancel | Complete |
| POST /api/runs/{id}/retry | Complete |
| DELETE /api/runs/{id} | Complete |
| DELETE /api/runs/cleanup/history | Complete |
| GET /api/runs/{id}/events | Complete |
| GET /api/runs/{id}/stream (SSE) | Complete |
| GET/POST /api/approvals | Complete |
| GET /api/approvals/stream (SSE) | Complete — real-time approval push |
| GET /api/approvals/{id} | Complete |
| POST /api/approvals/{id}/decision | Complete |
| GET/POST /api/agents | Complete |
| GET /api/agents/{id} | Complete — single agent detail |
| PUT /api/agents/{id} | Complete — update status/url/capabilities |
| DELETE /api/agents/{id} | Complete — 204 No Content |
| GET /api/actions | Complete — static catalog by channel |
| GET/DELETE /api/leases | Complete |
| GET/POST /api/projects | Complete |
| GET/PUT/DELETE /api/projects/{id} | Complete |
| POST /api/triggers/{id}/{ver} | Complete — upsert TriggerRegistration, wires cron scheduler |
| DELETE /api/triggers/{id}/{ver} | Complete — disable registration |
| GET /api/triggers | Complete — list all registrations |
| GET /api/triggers/{id}/{ver} | Complete — single registration |
| POST /api/triggers/{id}/{ver}/fire | Complete — manual fire with concurrency guard |
| POST /api/triggers/webhook/{id} | Complete — HMAC verify + dedupe + async run creation |
| POST /api/triggers/sync | Complete — scan procedures and auto-register triggers |

### Tests (backend/tests/) - 613 tests, all passing

| File | Tests | Scope |
|------|-------|-------|
| test_parser.py | 26 | All node types, step fields, error handlers, edge cases |
| test_validator.py | 16 | Valid/invalid procedures, all node reference checks |
| test_binder.py | 6 | Binding logic across node types |
| test_redaction.py | 12 | Sensitive field detection, nesting, depth limit, configurable patterns |
| test_metrics.py | 17 | Counters, histograms, labels, summary, reset |
| test_secrets.py | 11 | Env provider, manager, singleton, bulk get |
| test_graph.py | 13 | Graph service: all node types, layout, colors, edges |
| test_batch7.py | 15 | Global timeout, idempotency templates, error-handler dispatch |
| test_batch8.py | 9+ | Constraint UI validation, token-bucket rate limit, pagination |
| test_batch9.py | 20 | Run cancellation, LLM system_prompt/json_mode, approval expiry |
| test_batch10.py | 13 | wait_ms, telemetry tracking, provenance+retrieval_metadata |
| test_batch11.py | 17 | Status/effective_date enforcement, checkpoint_strategy, tag search, custom_metrics |
| test_batch12.py | 24+ | Agent capabilities parsing, AgentInstanceUpdate, projects CRUD, PUT/DELETE agents |
| test_batch13.py | 18 | _get_retry_config, step_timeout events, SLA breach, rate semaphore, alert webhook |
| test_batch14.py | 34 | Explain service, step retry config, LLM retry, is_checkpoint marker, checkpoint events |
| test_batch15.py | 7 | notify_on_error in IRErrorHandler |
| test_batch16.py | 25 | Server-side input_vars validation, step-level dry_run guard |
| test_execution_validation.py | 18 | Variables constraint enforcement (regex, min/max, allowed_values) |
| test_on_failure_handler.py | 5 | on_failure recovery handler routing |
| test_batch20.py | 26 | Trigger parsing, HMAC verification, payload hash, cron parsing, DB models, schemas, RunOut trigger fields |
| test_batch21.py | 47 | AWS Secrets Manager (string/binary/JSON/not-found/paginated), Azure Key Vault (key normalisation, not-found), HashiCorp Vault (KV v1/v2, AppRole, multi-field), CachingSecretsProvider (TTL hit/miss, invalidate), provider_from_config factory |
| test_batch22.py | 25 | Dynamic internal step timeout, screenshot_on_fail events, mock_external_calls/test_data_overrides, procedure search, checkpoint retention loop, file_watch trigger loop, GitHub Actions CI |
| test_batch23.py | 28 | Compiler: recursive subflow self-reference, template variable enforcement, action/channel compatibility; executor_dispatch: circuit-breaker skip; LLM estimated_cost_usd; projects: cost-summary endpoint |
| test_batch24.py | 27 | Parallel branch IR, checkpoint resume IR, approval decision flow service, subflow IR, LLM usage event structure; bugfix: execute_llm_action run_service scope |
| test_batch25.py | 34 | estimated_cost_usd schema/model, agent round-robin shuffle, screenshot_on_fail, mock_external_calls, test_data_overrides, dry_run mode, retention loop structural checks |
| test_batch26.py | 33 | SQLite/PG dialect support, Alembic setup, RunJob ORM, cancellation_requested column, checkpointer dialect-aware config |
| test_batch27.py | 31 | enqueue_run, requeue_run (UPDATE-or-INSERT for same run_id), worker loop poll/claim/execute/stall-reclaim, heartbeat lock renewal, DB-level run cancellation, embedded worker startup |
| test_api.py | 18 | API integration (run separately) |

### Frontend (frontend/src/) - 12 routes

| Route | Status | Notes |
|-------|--------|-------|
| / Dashboard | Working | Counts + recent runs + metrics panel |
| /procedures | Working | List + search + status/project filter + CKP import (with project assignment) |
| /procedures/[id] | Working | Overview/graph/CKP/versions tabs + input vars modal + provenance/retrieval_metadata |
| /procedures/[id]/[version] | Working | Edit CKP, delete version, start run + input vars modal + status/effective_date + version diff + **Trigger tab** (type selector, schedule/webhook/event config, HMAC secret, dedupe/concurrency controls, fire button) |
| /runs | Working | Status filters, date range, bulk cleanup, pagination, bulk select/cancel/delete |
| /runs/[id] | Working | Timeline + SSE live updates + artifacts (preview/download) + diagnostics + checkpoints + graph + retry-with-inputs modal |
| /approvals | Working | Inbox + inline approve/reject + SSE live updates |
| /approvals/[id] | Working | Full detail + decision form |
| /agents | Working | Card grid + capabilities checkboxes + Mark Online/Offline + Delete + action catalog |
| /leases | Working | Active lease table, force-release, expiry warning, auto-refresh |
| /projects | Working | List + create + inline edit + delete |
| (layout) | Working | Dark mode toggle, sidebar with pending-approval badge |

---

## CKP spec vs implementation matrix

### Top-level CKP fields

| Field | Parsed | Runtime Enforced | Gap |
|-------|--------|-----------------|-----|
| procedure_id | Yes | Yes | None |
| version | Yes | Yes | None |
| status | Yes | No | Not enforced at runtime |
| effective_date | Yes | No | Not used for version selection |
| trigger | No | No | Not parsed, not implemented |
| retrieval_metadata | **Yes** | No | Parsed + stored in DB; tag search supported |
| global_config.max_retries | Yes | Yes | Complete |
| global_config.retry_delay_ms | Yes | Yes | Complete |
| global_config.timeout_ms | Yes | **Yes** | `_invoke_graph_with_checkpointer` now wraps with `asyncio.wait_for`; raises `TimeoutError` on breach |
| global_config.on_failure | Yes | **Yes** | `_run_on_failure_handler` re-invokes graph from fallback node; success → run marked completed with `recovered_via` field |
| global_config.checkpoint_strategy | Yes | **Yes** | "none" disables checkpointer (Batch 11) |
| global_config.execution_mode | Yes | **Yes** | dry_run skips external steps; validation_only skips graph |
| global_config.rate_limiting | Yes | **Yes** | `max_concurrent_operations` → `asyncio.Semaphore` wraps all async node executors in graph_builder |
| global_config.secrets_config | Yes | Yes | Complete |
| global_config.audit_config | Yes | Yes | Redaction active |
| variables_schema | Yes | **Yes** | Defaults extracted; `required` validated before execution; regex/min/max/allowed_values enforced per-var |
| variables_schema.*.validation.sensitive | Yes | Yes | Redaction active |
| workflow_graph | Yes | Yes | Complete |
| provenance | **Yes** | No | Parsed + stored in DB (Batch 10) |

### Node-level fields

| Field | Parsed | Runtime Enforced | Gap |
|-------|--------|-----------------|-----|
| type (all 11) | Yes | Yes | Complete |
| agent | Yes | Yes | Complete |
| next_node | Yes | Yes | Complete |
| is_checkpoint | Yes | **Yes** | _checkpoint_node_id marker injected; checkpoint_saved event emitted |
| sla.max_duration_ms | Yes | **Yes** | Node execution timed; `sla_breached` event emitted when exceeded |
| sla.on_breach | Yes | **Yes** | `warn` logs, `fail` raises RuntimeError, `escalate` routes to `escalation_handler` node |
| sla.escalation_handler | Yes | **Yes** | When `on_breach=escalate`, state `next_node_id` set to handler node |
| telemetry.track_duration | Yes | **Yes** | `duration_ms` emitted in step_completed payload |
| telemetry.track_retries | Yes | **Yes** | `retry_count` emitted in step_completed payload |
| telemetry.custom_metrics | Yes | **Yes** | `record_custom_metric()` called per node after execution |
| idempotency_key | Yes | **Yes** | Template expressions evaluated via `render_template_str` before storage |
| error_handlers | Yes | **Yes** | retry/ignore/fail/escalate/fallback_node all dispatched in execute_sequence |

### Step-level fields

| Field | Parsed | Runtime Enforced | Gap |
|-------|--------|-----------------|-----|
| action | Yes | Yes | Complete |
| params (with templating) | Yes | Yes | Complete; `{{run_id}}` and `{{procedure_id}}` available as built-ins via `_build_template_vars()` |
| timeout_ms | Yes | **Yes** | `asyncio.wait_for` wraps internal, agent_http, and mcp_tool dispatch paths |
| wait_ms / wait_after_ms | Yes | **Yes** | asyncio.sleep enforced before/after each step |
| retry_on_failure | Yes | Yes | Complete (global policy) |
| output_variable | Yes | Yes | Complete |
| idempotency_key | Yes | **Yes** | Template key evaluated; composite key used for storage |

## Confirmed gaps by priority

### Priority 1 — Remaining functional gaps

| Gap | Detail | Effort |
|-----|--------|--------|
| ~~Step timeout for internal actions~~ | ✅ `timeout_ms` now enforced for all step types | Done |
| ~~`is_checkpoint` selective strategy~~ | ✅ `_checkpoint_node_id` marker + `checkpoint_saved` event (Batch 14) | Done |
| ~~Trigger automation~~ | ✅ Scheduler + webhook + trigger registry + dedupe/concurrency controls (Batch 20) | Done |
| AuthN/AuthZ hardening | Opt-in auth is implemented; remaining work is enable-by-default production profile, OIDC/SSO integration, and project-scoped authorization | Medium |

### Priority 2 — Technical debt / polish

| Item | Detail |
|------|--------|
| No server-side data fetching | All pages use `useEffect` + client fetch; no SWR/React Query caching |
| Frontend e2e tests | Playwright implemented (26 tests); needs broader edge/error/retry coverage |
| Workflow editor (frontend) hardening | Visual editor is shipped; remaining work is deeper validation UX, larger-flow performance tuning, and collaborative-edit safeguards |
| Retrieval metadata full-text search | `retrieval_metadata` parsed + stored in DB; no full-text search API |
| Artifact retention/cleanup | TTL cleanup loop and admin endpoints implemented; policy tuning and retention analytics can be expanded |
| `event_service.py` thin re-export | 6-line module re-exports from `run_service`; could be consolidated |

---

## Quick win completed checklist

### Batch 1 (2026-02-17)
1. Diagnostics API - GET /api/runs/{id}/diagnostics with idempotency, lease, event, retry data
2. Global retry policy - max_retries + retry_delay_ms with exponential backoff
3. Event redaction - pattern-based sensitive field sanitization in all event payloads
4. In-memory metrics - counters/histograms + GET /api/runs/metrics/summary
5. Checkpoint introspection API - list + inspect LangGraph checkpoints per run
6. Secrets provider - abstract base with env vars + Vault (hvac) implementations

### Batch 3 (2026-02-20) — Frontend UI completion
9. Toast notification system — `Toast.tsx` with `ToastProvider`/`useToast()`, 4 kinds, 3.5s auto-dismiss; injected globally via `layout.tsx`
10. Input variables modal — reads `variables_schema` from CKP JSON, typed inputs (string/number/array/object), JSON textarea for array/object with parse error toast, redirects to `/runs/{run_id}` after creation
11. Leases admin page — `/leases` route: live table with auto-refresh every 10s, force-release button, expiry-soon highlight, linked to run detail
12. Sidebar upgrades — inline SVG icons for all nav items, live pending-approval count badge (polls every 15s), `/leases` nav entry
13. Procedures list search — search bar filters by name + ID client-side, import success/error toast
14. Agents page toast — register success/error toast feedback
15. Run detail page links + toast — `<Link>` to procedure+version page, cancel/retry toast feedback

### Batch 4 (2026-02-20) — Backend correctness
16. Fix variables_schema default extraction — `execution_service.py` was spreading the raw schema dict into `vars`; now correctly extracts `default` values only
17. Required input variable validation — before graph execution, fails the run with clear error if any `required: true` variable is absent from `input_vars`
18. SLA breach monitoring — `graph_builder.py` wraps every async node executor with `asyncio` timing; if `sla.max_duration_ms` is exceeded, emits `sla_breached` run event

### Batch 5 (2026-02-20) — Backend validation + execution mode
19. Variables constraint validation — `_validate_var_constraints()` enforces `regex` (fullmatch), `min`, `max`, and `allowed_values` from each var's `validation` block before execution; 18 new tests in `test_execution_validation.py`
20. `execution_mode` enforcement — `dry_run` and `validation_only` modes skip graph execution and report success with a mode label after compile+validate+bind: operators can validate CKPs without running agents
21. SLA escalation/fail — `_check_sla` now returns a state patch when `on_breach=escalate` (sets `next_node_id` to `escalation_handler`); raises `RuntimeError` when `on_breach=fail`; LangGraph conditional router picks up the escalation node naturally

### Batch 6 (2026-02-20) — Error recovery + concurrency
22. `global_config.on_failure` routing — `_run_on_failure_handler()` re-invokes the graph from the designated recovery node when any error occurs (both in-graph errors and unhandled exceptions); 5 new tests in `test_on_failure_handler.py`
23. Step timeout for internal + MCP steps — `asyncio.wait_for` now applied to internal action calls and MCP tool dispatches in addition to agent_http (which already had it); raises `TimeoutError` with clear message
24. Rate limiting `max_concurrent_operations` — `build_graph` creates an `asyncio.Semaphore` when `rate_limiting.enabled=true` and `max_concurrent_operations>0`; all async node functions acquire it before executing

### Batch 7 (2026-02-21) — Global timeout, idempotency templates, error-handler action dispatch
25. Global `timeout_ms` enforcement — `_invoke_graph_with_checkpointer` accepts `timeout_ms: int | None`; wraps entire LangGraph `ainvoke` with `asyncio.wait_for`; raises `TimeoutError("… timed out after {N}ms …")` on breach; call site reads `ir.global_config.timeout_ms`; 4 new tests
26. Idempotency key template evaluation — `step.idempotency_key` is now rendered through `render_template_str(key, vs)` before being stored to DB, allowing patterns like `"{{run_id}}_{{customer_id}}"` for fine-grained dedup; 4 new tests
27. `error_handlers` action dispatch — replaced flat `for…else:raise` with explicit dispatch: `retry` applies handler's `max_retries`/`delay_ms` and restarts the while-retry loop; `fail`/`screenshot_and_fail` re-raise; `ignore` nulls output var and breaks; `escalate`/fallback_node routes state; also fixed latent bug where a matched handler without a fallback would restart the while loop instead of moving to next step; 7 new tests

### Batch 8 (2026-02-21) — Vars constraint UI, token-bucket rate limiting, run list pagination
28. Input variables constraint validation UI — both procedure pages validate on every keystroke and on submit: `required` fields show a red asterisk + "This field is required"; `regex` patterns tested with fullmatch with hint shown; `min`/`max` numeric bounds enforced; `allowed_values` renders a `<select>` dropdown; red border + inline error message per field; "Start Run" button disabled while any error is present
29. Token-bucket `max_requests_per_minute` — new `app/utils/token_bucket.py` with async-safe per-key `_Bucket`; `graph_builder.py` reads `rate_limiting.max_requests_per_minute` and calls `acquire_rate_limit()` at the top of each node's `_run()` closure; raises `RuntimeError` when limit cannot satisfy within 5 s; `reset_bucket()` for tests; 6 new tests
30. Runs list pagination — `run_service.list_runs` + `GET /api/runs` accept `limit` (default 100) and `offset`; `api.ts` forwards them; `/runs` page tracks `offset` state, renders "Load more" button when page is full, appends without resetting existing list; Refresh resets to page 1; 3 new tests

**Total tests after Batch 8: 186 (up from 177)**

### Batch 9 (2026-02-22) — Run cancellation propagation, LLM system_prompt/json_mode, approval expiry
31. Run cancellation propagation — new `app/utils/run_cancel.py` with in-process `asyncio.Event` registry per run (`register`, `mark_cancelled`, `is_cancelled`, `deregister`, `RunCancelledError`); `cancel_run` API calls `mark_cancelled(run_id)` before DB update; `execute_sequence` checks `is_cancelled` at the top of every step loop iteration and raises `RunCancelledError`; `execution_service.execute_run` catches `RunCancelledError` and persists `canceled` status; 8 new tests
32. LLM `system_prompt` + `json_mode` — `IRLlmActionPayload` gains `system_prompt: str | None` and `json_mode: bool`; `_parse_llm_action` reads both from the workflow JSON; `LLMClient.complete()` prepends a system-role message when set and adds `"response_format": {"type": "json_object"}` when `json_mode=True`; `execute_llm_action` made `async` (wraps blocking httpx call with `asyncio.to_thread`), added to `_NEEDS_DB`; 6 new tests
33. Approval expiry auto-timeout — `Approval` model gains `expires_at` column; `create_approval` accepts `timeout_ms` and computes deadline; new `get_expired_approvals(db)` query; `main.py` lifespan starts a background `asyncio.Task` (`_approval_expiry_loop`) that polls every 30 s and calls `submit_decision(…, "timeout")` for each expired pending approval; `execution_service` passes `timeout_ms` from awaiting_approval dict to `create_approval`; 6 new tests

**Total tests after Batch 9: 206 (up from 186)**

### Batch 10 (2026-02-17) — wait_ms/wait_after_ms, telemetry tracking, provenance + retrieval_metadata
34. `wait_ms` / `wait_after_ms` enforcement — `execute_sequence` now calls `asyncio.sleep(wait_ms / 1000)` before each step and `asyncio.sleep(wait_after_ms / 1000)` after each step when those fields are set on an `IRStep`; 3 new tests
35. Telemetry `track_duration` + `track_retries` — each `step_completed` event payload includes `duration_ms` (wall-clock ms since step start) when `node.telemetry.track_duration=true`, and `retry_count` when `node.telemetry.track_retries=true` and retries occurred; 3 new tests
36. `provenance` + `retrieval_metadata` parsing and storage — `IRProcedure` gains `provenance` and `retrieval_metadata` fields; `parse_ckp` reads both from the CKP JSON; `Procedure` model gains `provenance_json` and `retrieval_metadata_json` TEXT columns; `import_procedure` and `update_procedure` store them; `ProcedureDetail` schema exposes them as parsed dicts; 7 new tests

**Total tests after Batch 10: 219 (up from 206)**

### Batch 11 (2026-02-17) — Status enforcement, checkpoint_strategy, tag search, custom_metrics
37. Procedure `status` enforcement — `execute_run` rejects runs against `deprecated` or `archived` procedures with a clear `error` event; 2 new tests
38. `effective_date` enforcement — `execute_run` rejects runs where today's date is before the procedure's `effective_date`; gracefully ignores malformed dates; 3 new tests
39. `checkpoint_strategy="none"` — `build_graph` result is tagged with `_ckp_strategy`; `_invoke_graph_with_checkpointer` respects the tag and calls `graph.compile()` (no saver) when strategy is `"none"`, even when `CHECKPOINTER_URL` is configured; 3 new tests
40. Procedure tag search — `list_procedures` accepts optional `tags: list[str]`; post-filters by `retrieval_metadata.tags` requiring ALL requested tags to be present; `GET /api/procedures` accepts `tags` as comma-separated query param; 3 new tests
41. Procedure `status` filter — `list_procedures` accepts `status` query param that gets pushed into the SQL `WHERE` clause; API forwards it; 1 new test
42. `custom_metrics` telemetry emission — new `record_custom_metric(name, value, labels)` utility in `metrics.py`; `graph_builder.make_fn` reads `node.telemetry.custom_metrics` (list of strings or dicts) and calls `record_custom_metric` after each node executes; 5 new tests

**Total tests after Batch 11: 236 (up from 219)**

 - parser(27), validator(15), binder(6), redaction(21), metrics(17), secrets(11), graph(13), api(18) - all passing
8. Workflow graph viewer - GET /api/procedures/{id}/{version}/graph + React Flow frontend with custom CKP nodes, color-coding, minimap

### Batch 12 (2026-02-17) — Projects CRUD, agent capabilities/delete/health, frontend linkage fixes
43. **Projects CRUD** — `projects` DB table already existed; wired full CRUD: `GET/POST /api/projects`, `GET/PUT/DELETE /api/projects/{id}`; `/projects` frontend page with list/create/edit/delete; Procedures list now has project filter dropdown and project selector in import dialog; `listProcedures` API call accepts `project_id` param
44. **Agent capabilities in UI** — `AgentInstanceOut.capabilities` changed from `str|None` to `list[str]` with model_validator parsing comma-separated DB string; capabilities checkboxes in registration form driven by action catalog per channel; agent cards display capability pills
45. **Agent DELETE/PUT endpoints** — `DELETE /api/agents/{id}` (204) and `PUT /api/agents/{id}` (update status/url/concurrency/capabilities) added; frontend cards now have Mark Online/Offline and Delete buttons wired to these
46. **Agent health polling** — `_agent_health_loop()` background task in `main.py` pings `{base_url}/health` every 60 s via httpx, updates `agent.status` in DB when it changes
47. **Fixed 204 No Content parse crash** — `request<T>()` in `api.ts` was unconditionally calling `.json()` on all responses including 204 No Content — this caused `SyntaxError` on Delete Project, Delete Agent, and Revoke Lease. Fixed by checking `res.status === 204` before attempting JSON parse
48. **Fixed `importProcedure` project_id wiring** — `project_id` was being injected into the CKP body dict; fixed to pass as a sibling field `{ ckp_json, project_id }` matching `ProcedureCreate` schema

**Total tests after Batch 12: 260 (up from 236)**

### Batch 13 (2026-02-17) — Runtime correctness, observability, shared UI components
49. **`_get_retry_config` reads from `global_config`** — `_get_retry_config` now reads `state["global_config"]["retry_policy"]` (nested) or `state["global_config"]` top-level with fallback chain (max_retries, retry_delay_ms/delay_ms alias, backoff_multiplier) before falling back to hardcoded defaults; 6 new tests
50. **`global_config` in `OrchestratorState`** — `OrchestratorState` TypedDict gains `global_config: dict` field; `execution_service.execute_run` populates it with `ir.global_config` (including `_rate_semaphore` when rate limiting is enabled) before passing to `initial_state`
51. **`step_timeout` DB events** — all three binding paths in `execute_sequence` (internal, agent_http, mcp_tool) now call `record_step_timeout()` AND emit a `step_timeout` run event via `run_service.emit_event` before re-raising `TimeoutError`; operators can see timeouts in the run timeline
52. **SLA breach events (node-level)** — `execute_sequence` tracks node wall-clock time via `time.monotonic()`; after all steps complete, if `node.sla.max_duration_ms` was exceeded, emits a `sla_breached` run event with `actual_duration_ms`, `max_duration_ms`, and `on_breach` strategy; 1 integration test
53. **Rate limiting semaphore** — `execution_service` creates `asyncio.Semaphore(max_concurrent)` from `ir.global_config.rate_limiting.max_concurrent` (falls back to `settings.RATE_LIMIT_MAX_CONCURRENT`); injects it as `global_config["_rate_semaphore"]`; `execute_sequence` retrieves and acquires it per step; 3 new tests
54. **Alert webhook on `run_failed`** — `_fire_alert_webhook(run_id, error)` async function posts `{event, run_id, error}` to `settings.ALERT_WEBHOOK_URL` (fire-and-forget via `asyncio.ensure_future`); both `run_failed` emit paths in `execution_service` call it; no-op when URL not configured; 3 new tests
55. **Prometheus `/api/metrics` endpoint** — `GET /api/metrics` returns Prometheus text exposition format (counters + histograms with `_count`/`_sum`/quantiles); uses `PlainTextResponse`; scraper-compatible
56. **`record_step_execution/timeout/retry_attempt` module-level imports** — moved to top-level imports in `node_executors.py` (were missing, causing `NameError` at runtime); fixes regression in Batch 7 retry tests
57. **Shared UI badge components** — extracted 5 inline local component definitions:
    - `StatusBadge` → `@/components/shared/StatusBadge.tsx` (DaisyUI badge style; used by runs page + dashboard)
    - `ProcedureStatusBadge` → `@/components/shared/ProcedureStatusBadge.tsx` (pill style; used by 3 procedure pages)
    - `ApprovalStatusBadge` → `@/components/shared/ApprovalStatusBadge.tsx` (DaisyUI badge style; used by 2 approval pages)
58. **EventDot color map extended** — added `step_timeout: "bg-orange-500"`, `sla_breached: "bg-red-300"`, `node_error: "bg-red-500"`, `approval_expired: "bg-gray-500"` to the run detail timeline color map
59. **`notify_on_error` in IRErrorHandler** — when `error_handler.notify_on_error=True`, `execute_sequence` emits a `step_error_notification` run event (with `error_type`, `error`, and `handler_action` in payload) AND fire-and-forgets `_fire_alert_webhook`; DB emit failures are swallowed to never abort handler logic; 7 new tests in `test_batch15.py`
60. **Server-side `input_vars` validation** — new `app/utils/input_vars.py` module: `validate_input_vars(schema, input_vars)` mirrors frontend constraint rules (required, type coercion, allowed_values, regex fullmatch, min/max for numbers + strings); wired into `POST /api/runs` — returns HTTP 422 with `{message, errors}` when any field fails; 20 new tests across unit + API layers in `test_batch16.py`
61. **Step-level `execution_mode: dry_run`** — `execution_mode` added to `OrchestratorState` TypedDict and propagated from `ir.global_config` into `initial_state`; in `execute_sequence`, any step with `agent_http` or `mcp_tool` binding is intercepted before dispatch: sets stub result `{dry_run: True, skipped_action, binding}`, emits `dry_run_step_skipped` event, skips lease acquisition; `internal` bindings still execute normally; 5 new tests in `test_batch16.py`

**Total tests after Batch 16: 344 (up from 319)**

### Batch 17 (2026-02-18) — Frontend UX features + SSE approvals + configurable redaction
62. **Retry with modified inputs UI** — run detail retry button fetches procedure `variables_schema`, pre-fills with original inputs, opens modal with schema-aware form (select/textarea/input), validation, and submit via `createRun()`
63. **Procedure version diff viewer** — LCS-based `computeLineDiff()` algorithm, side-by-side comparison tool with color-coded diff hunks (red=removed, green=added)
64. **Artifact download/preview** — inline text/JSON preview via `ArtifactPreview` component + download button; auto-detects previewable files
65. **Bulk operations on runs list** — checkbox column, `toggleSelect`/`toggleSelectAll`, bulk cancel/delete with `ConfirmDialog`
66. **SSE for approvals** — `GET /api/approvals/stream` SSE endpoint polls DB every 2s and pushes `approval_update` events; frontend subscribes via `subscribeToApprovalUpdates()`; replaces 10s polling
67. **Configurable redaction policy** — `build_patterns(extra_fields)` merges default patterns with CKP-specified field patterns; `emit_event(extra_redacted_fields=...)` passes through to redaction
68. **Dead code cleanup** — removed `@heroicons/react` from `package.json` (verified zero imports)
69. **Dark mode toggle** — `ThemeProvider` context with `useTheme()` hook, localStorage persistence, system preference detection; header sun/moon toggle; `dark:` classes on Sidebar + Header

### Batch 18 (2026-02-18) — Fixes + doc reconciliation
70. **GET /api/agents/{agent_id}** — added missing endpoint (router had PUT/DELETE but no GET; `test_agent_not_found` was getting 405 instead of 404)
71. **Documentation reconciliation** — updated FUTURE_PLAN.md and IMPLEMENTATION_STATUS.md to reflect actual implementation state across all 18 batches

**Total tests after Batch 18: 362 (up from 344)**

### Batch 32 (2026-02-23) — Sprint 6: Auth, pool round-robin, metrics export, secrets rotation, metadata search

92. **AuthN/AuthZ package** — `app/auth/` package: `deps.py` (`get_current_user`, `Principal` dataclass supporting `Bearer JWT` + `X-API-Key`), `roles.py` (`require_role()` dependency factory with role hierarchy `viewer < approver < operator < admin`); `AUTH_ENABLED=false` default — zero-breaking rollout; anonymous admin returned when disabled
93. **Auth config settings** — `AUTH_ENABLED`, `AUTH_SECRET_KEY`, `AUTH_TOKEN_EXPIRE_MINUTES`, `API_KEYS` added to `Settings`
94. **Role guards wired to routers** — `operator` guard on all mutating endpoints in `runs.py`, `procedures.py`, `agents.py`; `approver` guard on `POST /api/approvals/{id}/decision`; `admin` guard on destructive cleanup; `decided_by` auto-set from `principal.identity` when body field is blank
95. **Token issuance endpoint** — `app/api/auth.py`: `POST /api/auth/token` (HS256 JWT with `sub` + `roles` claims, shared-secret body auth); only active when `AUTH_ENABLED=true`
96. **Agent `pool_id` + round-robin** — `pool_id: str | None` column added to `AgentInstance`; `executor_dispatch._find_capable_agent` replaced `random.shuffle` with per-pool `_pool_counters` monotonic round-robin; counters keyed `"{channel}:{pool_id or 'standalone'}"`; `AgentInstanceCreate/Update/Out` schemas + `register_agent`/`update_agent` handlers updated
97. **Migration v003** — `alembic/versions/v003_agent_pool_id.py`: adds `pool_id VARCHAR(128)` + `ix_agent_instances_pool_id` index
98. **Prometheus Pushgateway export** — `METRICS_PUSH_URL`, `METRICS_PUSH_INTERVAL_SECONDS`, `METRICS_PUSH_JOB` config; `_metrics_push_loop()` background task pushes Prometheus text to pushgateway PUT API; `to_prometheus_text()` extracted as shared serializer; `GET /api/metrics` now uses it; p95 percentile added to histogram stats
99. **Secret rotation cache flush** — `invalidate_secrets_cache()` global helper in `secrets_service.py`; `SECRETS_ROTATION_CHECK=true` triggers flush + `secrets_cache_invalidated` run event before each run execution; `invalidate_secrets_cache` imported in `execution_service.py`
100. **`metadata_search` SQL LIKE** — `GET /api/procedures?metadata_search=<query>` adds `WHERE retrieval_metadata_json ILIKE '%query%'` at DB level (bypasses Python in-memory filter for large datasets); `list_procedures` service signature extended

**Tests unchanged: 681 (all passing — `AUTH_ENABLED=false` means all existing tests continue working)**

### Batch 31 (2026-02-22) — Pre-production hardening
86. **`delete_run` + `cleanup_runs_before` RunJob cascade** — both functions now delete `run_jobs` rows before deleting the parent `Run` row; previously caused a FK constraint violation on PostgreSQL and silent orphan records on SQLite
87. **Runs query composite indexes** — new Alembic migration `v002_runs_indexes` adds `ix_runs_status_created_at`, `ix_runs_project_created_at`, `ix_runs_procedure_created_at`; speeds up all `GET /api/runs` filter/sort paths at scale
88. **Diagnostics SQL optimization** — `get_run_diagnostics` replaced full-row event loads with `func.count()` aggregate queries and filters active leases to `released_at IS NULL` only
89. **Diagnostics UI field alignment** — `StepIdempotencyDiagnostic.completed_at` → `updated_at` in `types.ts`; run detail idempotency table now renders correct timestamp
90. **e2e tsconfig cross-OS safety** — added `forceConsistentCasingInFileNames: true` to `frontend/e2e/tsconfig.json`
91. **Doc-drift cleanup** — stale deferred entries in `IMPLEMENTATION_SPEC.md`, `IMPLEMENTATION_STATUS.md`, `FUTURE_PLAN.md` corrected to match shipped state

**Tests unchanged: 681 (all passing)**

### Batch 30 (2026-02-21) — Artifact retention/TTL + frontend e2e
72. **SQLite/PostgreSQL dual-dialect engine** — `config.py` detects dialect from `ORCH_DB_URL`; `engine.py` creates `aiosqlite` or `asyncpg` engine accordingly; checkpointer is dialect-aware; `WORKER_EMBEDDED` defaults to `True` for SQLite (single-process) and `False` for PostgreSQL (external worker)
73. **Alembic migrations setup** — `alembic.ini` + `alembic/env.py` with `sync_db_url()` helper; `v001_initial_schema` migration covers all tables including `run_jobs`; `asyncpg` + `alembic` added to `requirements.txt`
74. **`RunJob` ORM model** — `run_jobs` table: `job_id` (PK), `run_id` (UNIQUE FK), `status`, `priority`, `attempts`, `max_attempts`, `locked_by`, `locked_until`, `available_at`, `error_message`
75. **`cancellation_requested` column on `Run`** — `INTEGER NOT NULL DEFAULT 0`; DB-level flag readable by worker processes across restarts without in-memory state

**Total tests after Batch 26: 582 (up from 549)**

### Batch 27 (2026-02-21) — Full durable worker model + approval-resume bug fix
76. **`app/worker/` package** — `enqueue.py` (`enqueue_run` sync for new runs), `loop.py` (full poll/claim/execute cycle with SQLite optimistic locking and PostgreSQL `FOR UPDATE SKIP LOCKED`), `heartbeat.py` (lock-renewal task bridges DB `cancellation_requested → asyncio.Event`), `worker_main.py` (standalone CLI entrypoint for external worker processes)
77. **Stalled-job recovery** — `reclaim_stalled_jobs()` finds `status=running AND locked_until < now`; resets to `retrying` (with exponential delay) or marks `failed` when `max_attempts` exceeded; called at the top of every poll cycle
78. **Embedded worker** — `main.py` lifespan starts `asyncio.create_task(_worker_loop())` when `settings.WORKER_EMBEDDED=True`; task is cancelled cleanly on shutdown
79. **`requeue_run()` approval-resume + retry fix** — async SELECT-then-UPDATE-or-INSERT replaces blind INSERT that was violating the UNIQUE constraint on `run_jobs.run_id`; `approvals.py` and `runs.py` retry path both call `requeue_run()`; approval decisions no longer silently discarded on duplicate key
80. **API wiring** — `POST /api/runs` calls `enqueue_run()` for new runs; `POST /api/approvals/{id}/decision` calls `requeue_run(priority=10)` to fast-track resumed runs; `POST /api/runs/{id}/retry` calls `requeue_run()`

**Total tests after Batch 27: 613 (up from 582)**

### Batch 28 (2026-02-21) — Run-scoped artifact paths + built-in template variables
81. **`_build_template_vars(state)` helper** — new function in `node_executors.py`; replaces all 7 `vs = dict(state.get("vars", {}))` calls across every node executor; calls `setdefault("run_id", ...)` and `setdefault("procedure_id", ...)` so user-defined variables always take precedence; makes `{{run_id}}` and `{{procedure_id}}` available in any CKP step parameter without declaring them in `variables_schema`
82. **Run-scoped artifact storage** — artifact files now saved to `artifacts/{run_id}/filename` subfolders; prevents multiple runs from overwriting each other's files; demonstrated in `books_price_monitor.ckp.json` v1.0.3 with `"path": "artifacts/{{run_id}}/books_monitor_screenshot.png"`; served at `GET /api/artifacts/{run_id}/filename` via FastAPI `StaticFiles` mount

**Total tests after Batch 28: 613** (no new tests — change is runtime wiring; existing executor tests cover the affected paths)

### Batch 29 (2026-02-21) — HA-safe scheduling via DB-level leader election
83. **`SchedulerLeaderLease` ORM model** — new table `scheduler_leader_leases` (`name` PK, `leader_id`, `acquired_at`, `expires_at`) added to `app/db/models.py`; `v001_initial_schema` Alembic migration updated; SQLite `CREATE TABLE IF NOT EXISTS` guard added to `main.py` lifespan idempotent migrations
84. **`app/runtime/leader.py` — `LeaderElection` class** — three-path algorithm: (1) renew own row via `UPDATE WHERE leader_id=self`, (2) steal expired row via `UPDATE WHERE expires_at < now`, (3) acquire fresh row via `INSERT` (catches `IntegrityError` on concurrent conflict); TTL 60s; renewal every 15s; `is_leader` property; `start()` / `stop()` lifecycle; `leader_election` module-level singleton; `leader_id` generated as `hostname-pid-rand` for uniqueness; `start()` launched in `lifespan()` before all singleton background tasks; SQLite always wins immediately (single process); PostgreSQL races correctly under multi-replica
85. **Singleton background loops are leader-gated** — `TriggerScheduler.sync_schedules()` returns early if `leader_election.is_leader` is False; `_fire_scheduled_trigger()` returns early if not leader (belt-and-suspenders alongside trigger-service dedupe guard); `_file_watch_trigger_loop()` skips poll and clears cached mtimes when not leader (prevents spurious fires on leadership transition); `_approval_expiry_loop()` skips when not leader (prevents double-timeout of same approval across replicas)

**Total tests after Batch 29: 668 (up from 613; +18 Batch 29 leader election tests, +37 tests attributed to other batches on recount)**

---

## Suggested next quick wins (from audit)

| # | Item | Effort | Impact | Status |
|---|------|--------|--------|--------|
| 25 | Global `timeout_ms` enforcement | Small | Medium | ✅ Done (Batch 7) |
| 26 | Idempotency key template evaluation | Small | Medium | ✅ Done (Batch 7) |
| 27 | Variables regex validation UI | Small | Medium | ✅ Done (Batch 8) |
| 28 | `error_handlers` action semantics | Medium | Medium | ✅ Done (Batch 7) |
| 29 | Trigger automation | Large | High | ✅ Done (Batch 20) |
| 30 | Rate-limit `max_requests_per_minute` | Medium | Low | ✅ Done (Batch 8) |
| 31 | Configurable redaction policy | Small | Medium | ✅ Done (Batch 17) |
| 32 | Dark mode | Small | Medium | ✅ Done (Batch 17) |
| 33 | SSE for approvals | Medium | High | ✅ Done (Batch 17) |
| 34 | Artifact preview/download | Small | Medium | ✅ Done (Batch 17) |
| 35 | Bulk operations on runs | Medium | Medium | ✅ Done (Batch 17) |
| 36 | Durable worker model | Large | High | ✅ Done (Batch 27) |
| 37 | `{{run_id}}` built-in template variable | Small | Medium | ✅ Done (Batch 28) |
| 38 | Run-scoped artifact paths | Small | Medium | ✅ Done (Batch 28) |
| 39 | Artifact retention/TTL cleanup | Small | Medium | ✅ Done (Batch 30) |
| 40 | Frontend e2e tests (Playwright) | Large | High | ✅ Done (Batch 30, 26 tests) |
| 41 | AuthN/AuthZ + role model | Large | Critical | ✅ Done as opt-in baseline (Batch 32); production hardening follow-ups remain |
| 42 | HA-safe scheduling (leader election) | Small | High | ✅ Done (Batch 29) |

---

## References

- Full roadmap: FUTURE_PLAN.md
- CKP syntax: ckp_file-main/ckp_file_syntex.txt
- Implementation spec: IMPLEMENTATION_SPEC.md
- Main README: README.md
