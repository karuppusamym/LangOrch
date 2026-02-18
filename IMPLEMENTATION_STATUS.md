# LangOrch Implementation Status

Last updated: 2026-02-17 (Batch 13: _get_retry_config from global_config, step_timeout events, SLA breach events, rate semaphore, alert webhook, Prometheus endpoint, shared UI components — 278 tests)

This document is the single authoritative source for **what is implemented vs what is missing**, derived from direct code analysis of all backend and frontend source files.

---

## Summary scorecard

| Domain | Spec Coverage | Implementation | Status |
|--------|---------------|----------------|---------|
| CKP compiler (parse → validate → bind) | 100% | 95% | Complete |
| CKP top-level fields (trigger, provenance) | 100% | 70% | trigger not parsed; provenance parsed+stored |
| All 11 node type executors | 100% | 100% | Complete |
| Global config enforcement | 100% | 85% | timeout, on_failure, rate_limit, execution_mode, vars_schema all enforced |
| Policy: retry/backoff | 100% | 100% | Complete |
| Policy: timeout/SLA (global) | 100% | 100% | asyncio.wait_for wraps full graph invocation |
| Policy: timeout/SLA (step-level) | 100% | 40% | Agent+MCP steps timed; internal steps not |
| Policy: rate limiting | 100% | 80% | max_concurrent_operations + max_requests_per_minute both enforced |
| Trigger automation | 100% | 0% | Not started |
| Checkpointing + replay | 100% | 95% | checkpoint_strategy="none" supported; replay working |
| Step idempotency | 100% | 95% | Template key evaluation implemented |
| Multi-agent concurrency (leases) | 100% | 95% | Near-complete |
| Human-in-the-loop | 100% | 100% | Approval expiry auto-timeout implemented |
| Secrets provider (env + Vault) | 100% | 80% | Working; AWS/Azure stubs |
| Observability (events + SSE) | 100% | 95% | Near-complete |
| Observability (in-memory metrics) | 100% | 100% | Prometheus `/api/metrics` text endpoint added |
| Observability (telemetry fields) | 100% | 50% | track_duration+track_retries emitted; custom_metrics recorded |
| Redaction | 100% | 90% | Implemented |
| Diagnostics API | 100% | 100% | Complete |
| Checkpoint introspection API | 100% | 100% | Complete |
| Graph extraction API | 100% | 100% | Complete |
| Projects CRUD | 100% | 100% | Complete — backend + frontend |
| Agent capabilities + health polling | 100% | 100% | Complete — capabilities in UI, health loop polls /health |
| Agent management (update/delete) | 100% | 100% | PUT/DELETE endpoints + frontend buttons |
| Frontend: core CRUD pages (10 routes) | 100% | 100% | Complete |
| Frontend: projects page | 100% | 100% | Complete — list/create/edit/delete |
| Frontend: workflow graph viewer | 100% | 95% | Implemented |
| Frontend: diagnostics/metrics pages | 100% | 100% | Complete |
| Frontend: input variables form | 100% | 100% | Complete — constraint validation in UI |
| Frontend: toast notification system | 100% | 100% | Complete |
| Frontend: leases admin page | 100% | 100% | Complete |
| Frontend: status/filter/metadata display | 100% | 100% | Complete |
| Frontend: agent capabilities display | 100% | 100% | Complete |
| Frontend: project filter in procedures | 100% | 100% | Complete |
| Frontend: workflow builder/editor | 100% | 0% | Not started |
| Frontend→Backend API linkage | 100% | 100% | All 35+ call sites verified; 204-body bug fixed |
| Backend tests (unit) | Target | 98% | **278 tests** — all passing |
| Backend tests (integration) | Target | 35% | 18 API tests |
| Frontend tests | Target | 0% | Not started |
| AuthN/AuthZ | Target | 0% | Not started (parked) |
| CI/CD pipeline | Target | 0% | Not started |

---

## What is fully implemented (confirmed by code audit)

### CKP Compiler pipeline (backend/app/compiler/)
- parser.py: all 11 node types, all step fields, error_handlers, SLA, telemetry, idempotency_key
- validator.py: procedure_id, version, start_node, dangling node references for all node types, multi-error collection
- binder.py: compile-time action binding (internal vs external)
- ir.py: 20 dataclasses covering all CKP constructs

### Runtime execution engine (backend/app/runtime/)
- All 11 node executors (node_executors.py, 1097 lines): sequence, logic, loop, parallel, processing, verification, llm_action, human_approval, transform, subflow, terminate
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
- Template engine: path.to.var expansion, dotted paths, defaults, recursive dict/list
- Safe expression evaluator: 12 operators, no eval(), boolean/number coercion

### Services (backend/app/services/) - 9 services
- execution_service.py: full pipeline: compile, validate, bind, load secrets, build graph, checkpoint-invoke, persist artifacts, update metrics
- secrets_service.py: EnvironmentSecretsProvider (working), VaultSecretsProvider (working with hvac), AWS/Azure stubs
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

### Database (backend/app/db/) - 9 tables
projects, procedures, runs, run_events, approvals, step_idempotency, artifacts, agent_instances, resource_leases

### API layer - 26 endpoints confirmed

| Endpoint | Status |
|----------|--------|
| GET /api/health | Complete |
| GET /api/metrics | Complete — Prometheus text exposition format |
| POST/GET /api/procedures | Complete |
| GET /api/procedures/{id}/versions | Complete |
| GET/PUT/DELETE /api/procedures/{id}/{version} | Complete |
| GET /api/procedures/{id}/{version}/graph | Complete |
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
| GET /api/approvals/{id} | Complete |
| POST /api/approvals/{id}/decision | Complete |
| GET/POST /api/agents | Complete |
| PUT /api/agents/{id} | Complete — update status/url/capabilities |
| DELETE /api/agents/{id} | Complete — 204 No Content |
| GET /api/actions | Complete — static catalog by channel |
| GET/DELETE /api/leases | Complete |
| GET/POST /api/projects | Complete |
| GET/PUT/DELETE /api/projects/{id} | Complete |
| POST /api/triggers | NOT IMPLEMENTED |

### Tests (backend/tests/) - 260 tests, all passing

| File | Tests | Scope |
|------|-------|-------|
| test_parser.py | 27 | All node types, step fields, error handlers, edge cases |
| test_validator.py | 15 | Valid/invalid procedures, all node reference checks |
| test_binder.py | 6 | Binding logic across node types |
| test_redaction.py | 21 | Sensitive field detection, nesting, depth limit |
| test_metrics.py | 17 | Counters, histograms, labels, summary, reset |
| test_secrets.py | 11 | Env provider, manager, singleton, bulk get |
| test_graph.py | 13 | Graph service: all node types, layout, colors, edges |
| test_batch7.py | 15 | Global timeout, idempotency templates, error-handler dispatch |
| test_batch8.py | 12 | Constraint UI validation, token-bucket rate limit, pagination |
| test_batch9.py | 20 | Run cancellation, LLM system_prompt/json_mode, approval expiry |
| test_batch10.py | 13 | wait_ms, telemetry tracking, provenance+retrieval_metadata |
| test_batch11.py | 17 | Status/effective_date enforcement, checkpoint_strategy, tag search, custom_metrics |
| test_batch12.py | 30 | Agent capabilities parsing, AgentInstanceUpdate, projects CRUD, PUT/DELETE agents |
| test_batch13.py | 18 | _get_retry_config from global_config, step_timeout events, SLA breach, rate semaphore, alert webhook, OrchestratorState.global_config |
| test_api.py | 18 | API integration (excluded from unit suite; run separately) |

### Frontend (frontend/src/) - 9 routes

| Route | Status | Notes |
|-------|--------|-------|
| / Dashboard | Working | Counts + recent runs + metrics panel |
| /procedures | Working | List + search + status/project filter + CKP import (with project assignment) |
| /procedures/[id] | Working | Overview/graph/CKP/versions tabs + input vars modal + provenance/retrieval_metadata |
| /procedures/[id]/[version] | Working | Edit CKP, delete version, start run + input vars modal + status/effective_date |
| /runs | Working | Status filters, date range, bulk cleanup, pagination |
| /runs/[id] | Working | Timeline + SSE live updates + artifacts + diagnostics + toast + graph link |
| /approvals | Working | Inbox + inline approve/reject |
| /approvals/[id] | Working | Full detail + decision form |
| /agents | Working | Card grid + capabilities checkboxes + Mark Online/Offline + Delete + action catalog |
| /leases | Working | Active lease table, force-release, expiry warning, auto-refresh |
| /projects | Working | List + create + inline edit + delete |

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
| retrieval_metadata | No | No | Not parsed, not stored |
| global_config.max_retries | Yes | Yes | Complete |
| global_config.retry_delay_ms | Yes | Yes | Complete |
| global_config.timeout_ms | Yes | **Yes** | `_invoke_graph_with_checkpointer` now wraps with `asyncio.wait_for`; raises `TimeoutError` on breach |
| global_config.on_failure | Yes | **Yes** | `_run_on_failure_handler` re-invokes graph from fallback node; success → run marked completed with `recovered_via` field |
| global_config.checkpoint_strategy | Yes | No | Parsed, not used |
| global_config.execution_mode | Yes | No | dry_run/validation not respected |
| global_config.rate_limiting | Yes | **Yes** | `max_concurrent_operations` → `asyncio.Semaphore` wraps all async node executors in graph_builder |
| global_config.secrets_config | Yes | Yes | Complete |
| global_config.audit_config | Yes | Yes | Redaction active |
| variables_schema | Yes | **Yes** | Defaults extracted; `required` validated before execution; regex/min/max/allowed_values enforced per-var |
| variables_schema.*.validation.sensitive | Yes | Yes | Redaction active |
| workflow_graph | Yes | Yes | Complete |
| provenance | No | No | Not parsed |

### Node-level fields

| Field | Parsed | Runtime Enforced | Gap |
|-------|--------|-----------------|-----|
| type (all 11) | Yes | Yes | Complete |
| agent | Yes | Yes | Complete |
| next_node | Yes | Yes | Complete |
| is_checkpoint | Yes | No | Field stored, not used for selective checkpointing |
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
| params (with templating) | Yes | Yes | Complete |
| timeout_ms | Yes | **Partial** | Agent + MCP steps wrapped with asyncio.wait_for; internal/transform steps not timed |
| wait_ms / wait_after_ms | Yes | **Yes** | asyncio.sleep enforced before/after each step |
| retry_on_failure | Yes | Yes | Complete (global policy) |
| output_variable | Yes | Yes | Complete |
| idempotency_key | Yes | **Yes** | Template key evaluated; composite key used for storage |

## Confirmed gaps by priority

### Priority 1 — Remaining functional gaps

| Gap | Detail | Effort |
|-----|--------|--------|
| Step timeout for internal actions | `timeout_ms` not enforced for transform/sequence internal steps (agent and MCP are timed) | Small |
| `is_checkpoint` selective strategy | `is_checkpoint=true` on nodes should trigger a forced checkpoint; currently ignored | Small |
| Trigger automation | `trigger` field not parsed; no scheduler/webhook/event-driven execution | Large |
| AuthN/AuthZ | No identity enforcement; all endpoints open | Large (parked) |

### Priority 2 — Technical debt / polish

| Item | Detail |
|------|--------|
| Duplicate UI components | StatusBadge extracted to `@/components/shared/StatusBadge.tsx`; ProcedureStatusBadge to `@/components/shared/ProcedureStatusBadge.tsx`; ApprovalStatusBadge to `@/components/shared/ApprovalStatusBadge.tsx` — all inline definitions removed |
| AWS/Azure secrets stubs | Both providers fall back to env vars with a warning log |
| No server-side data fetching | All pages use `useEffect` + client fetch; no SWR/React Query caching |
| Metrics export | Prometheus `/api/metrics` text format endpoint added |
| Frontend e2e tests | No Playwright/Cypress tests |
| CI/CD pipeline | No lint/test/build gates |
| Workflow editor (frontend) | Read-only graph viewer done; editable properties not started |
| Retrieval metadata search | retrieval_metadata not parsed; no search API | Medium |

### Priority 4 - Technical debt

| Item | Detail |
|------|--------|
| Duplicate UI components | StatusBadge and ApprovalStatusBadge extracted to `src/components/shared/` — inline definitions removed from all 7 files |
| Dead frontend code | getActionCatalog() in api.ts, ActionCatalog type, Project type - never used |
| Dead npm dependency | @heroicons/react listed in package.json but never imported |
| event_service.py is 6-line re-export | Could be consolidated into run_service.py |
| AWS/Azure secrets stubs | Providers fall back to env vars with warning |
| No error toast system | ~~Errors are console.error/alert() - no formal notification UX~~ **DONE** — `Toast.tsx` with `ToastProvider` + `useToast()` hook, 4 types, auto-dismiss |
| All pages use useEffect only | No server-side data fetching, no caching (SWR/React Query) |

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

**Total tests after Batch 13: 278 (up from 260)**

---

## Suggested next quick wins (from audit)

| # | Item | Effort | Impact | Status |
|---|------|--------|--------|--------|
| 25 | Global `timeout_ms` enforcement — wrap entire graph invocation with `asyncio.wait_for` | Small | Medium | ✅ Done (Batch 7) |
| 26 | Idempotency key template evaluation — evaluate `{{var}}` expressions in step-level `idempotency_key` | Small | Medium | ✅ Done (Batch 7) |
| 27 | Variables regex validation UI — surface constraint errors in the input vars modal | Small | Medium | ✅ Done (Batch 8) |
| 28 | `error_handlers` action semantics — `retry`, `escalate`, `ignore`, `fail`, `screenshot_and_fail` fully dispatched | Medium | Medium | ✅ Done (Batch 7) |
| 29 | Trigger automation — parse trigger field; add scheduler + webhook receiver | Large | High | Pending |
| 30 | Rate-limit `max_requests_per_minute` — a token-bucket per procedure to throttle step invocations | Medium | Low | ✅ Done (Batch 8) |

---

## References

- Full roadmap: FUTURE_PLAN.md
- CKP syntax: ckp_file-main/ckp_file_syntex.txt
- Implementation spec: IMPLEMENTATION_SPEC.md
- Main README: README.md
