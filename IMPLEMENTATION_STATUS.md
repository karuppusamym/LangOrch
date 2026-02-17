# LangOrch Implementation Status

Last updated: 2026-02-17

This document provides a complete mapping of **CKP specification → current implementation → remaining gaps**, organized for development planning.

---

## Quick reference

| Domain | Spec Coverage | Implementation | Priority |
|--------|---------------|----------------|----------|
| CKP parser (top-level fields) | 100% | 60% | High |
| CKP node types | 100% | 100% | Complete |
| Global config enforcement | 100% | 50% | High |
| Policy enforcement (retry/SLA/timeout) | 100% | 60% | High |
| Trigger automation | 100% | 0% | High |
| Checkpointing + replay | 100% | 95% | Medium |
| Step idempotency | 100% | 85% | Medium |
| Multi-agent concurrency | 100% | 90% | Medium |
| Human-in-the-loop | 100% | 80% | Medium |
| Secret management | 100% | 80% | Medium |
| Observability (events) | 100% | 90% | Medium |
| Observability (metrics/telemetry) | 100% | 40% | High |
| Audit trail | 100% | 80% | Medium |
| Frontend workflow graph viewer | 100% | 90% | Complete |
| Frontend workflow builder | 100% | 0% | Medium |
| Frontend diagnostics | 100% | 30% | High |
| Automated tests | Target | 70% | Medium |
| CI/CD pipeline | Target | 0% | Medium |

---

## CKP specification vs implementation matrix

### Top-level CKP fields

| Field | CKP Spec | Parsed by IR | Stored in DB | Runtime Use | Gap |
|-------|----------|--------------|--------------|-------------|-----|
| `procedure_id` | ✅ | ✅ | ✅ | ✅ | None |
| `version` | ✅ | ✅ | ✅ | ✅ | None |
| `status` | ✅ | ✅ | ✅ | ❌ | Not enforced in runtime |
| `effective_date` | ✅ | ✅ | ✅ | ❌ | Not used for version selection |
| `trigger` | ✅ | ❌ | ❌ | ❌ | **Not implemented** |
| `trigger.type` | ✅ manual/scheduled/webhook/event/file_watch | ❌ | ❌ | ❌ | No scheduler/webhook |
| `retrieval_metadata` | ✅ | ❌ | ❌ | ❌ | **Not implemented** |
| `global_config` | ✅ (shallow) | ✅ (shallow) | ✅ | ⚠️ | Parsed but not enforced |
| `global_config.max_retries` | ✅ | ✅ | ✅ | ✅ | Complete |
| `global_config.retry_delay_ms` | ✅ | ✅ | ✅ | ✅ | Complete |
| `global_config.timeout_ms` | ✅ | ✅ | ✅ | ❌ | Not enforced globally |
| `global_config.checkpoint_strategy` | ✅ | ✅ | ✅ | ❌ | Not respected |
| `global_config.execution_mode` | ✅ dry_run/validation | ✅ | ✅ | ❌ | Not respected |
| `global_config.rate_limiting` | ✅ | ✅ | ✅ | ❌ | Not enforced |
| `global_config.secrets_config` | ✅ | ✅ | ✅ | ✅ | Complete (env_vars, Vault) |
| `global_config.audit_config` | ✅ | ✅ | ✅ | ✅ | Complete with redaction |
| `variables_schema` | ✅ | ✅ | ✅ | ⚠️ | Parsed, validation not enforced |
| `variables_schema.validation.regex` | ✅ | ✅ | ✅ | ❌ | Not validated at bind time |
| `variables_schema.validation.sensitive` | ✅ | ✅ | ✅ | ✅ | Redaction implemented |
| `workflow_graph` | ✅ | ✅ | ✅ | ✅ | Complete |
| `provenance` | ✅ | ❌ | ❌ | ❌ | **Not implemented** |

### Node-level fields

| Field | CKP Spec | Parsed | Runtime Enforced | Gap |
|-------|----------|--------|------------------|-----|
| `type` | ✅ 11 types | ✅ | ✅ | Complete |
| `agent` | ✅ | ✅ | ✅ | Complete |
| `next_node` | ✅ | ✅ | ✅ | Complete |
| `is_checkpoint` | ✅ | ✅ | ❌ | Not used for selective checkpointing |
| `sla.max_duration_ms` | ✅ | ✅ | ❌ | **Not monitored** |
| `sla.on_breach` | ✅ | ✅ | ❌ | **Not acted upon** |
| `telemetry.track_duration` | ✅ | ✅ | ❌ | **No metrics export** |
| `telemetry.custom_metrics` | ✅ | ✅ | ❌ | **No metrics export** |
| `idempotency_key` | ✅ | ✅ | ⚠️ | Stored, custom templates not supported |

### Node type implementations

| Type | Parsed | Executor | Graph Wiring | Edge Cases | Status |
|------|--------|----------|--------------|------------|--------|
| `sequence` | ✅ | ✅ | ✅ | ✅ Idempotency + leases | Complete |
| `logic` | ✅ | ✅ | ✅ | ✅ Conditional routing | Complete |
| `loop` | ✅ | ✅ | ✅ | ✅ Iteration state | Complete |
| `parallel` | ✅ | ✅ | ✅ | ✅ Branch execution | Complete |
| `processing` | ✅ | ✅ | ✅ | ✅ Operation dispatch | Complete |
| `verification` | ✅ | ✅ | ✅ | ✅ Check routing | Complete |
| `llm_action` | ✅ | ✅ | ✅ | ⚠️ Retry deep policy missing | Mostly complete |
| `human_approval` | ✅ | ✅ | ✅ | ✅ Pause/resume | Complete |
| `transform` | ✅ | ✅ | ✅ | ✅ Variable mapping | Complete |
| `subflow` | ✅ | ✅ | ✅ | ✅ Nested execution | Complete |
| `terminate` | ✅ | ✅ | ✅ | ✅ Cleanup dispatch | Complete |

### Step-level features

| Feature | CKP Spec | Implementation | Gap |
|---------|----------|----------------|-----|
| `action` dispatch | ✅ | ✅ | Complete |
| `params` templating | ✅ | ✅ | Complete |
| `timeout_ms` | ✅ | ✅ | ❌ Not enforced per step |
| `wait_ms` / `wait_after_ms` | ✅ | ✅ | Complete |
| `retry_on_failure` | ✅ | ✅ | ⚠️ Boolean only, no deep policy |
| `output_variable` | ✅ | ✅ | Complete |
| `idempotency_key` | ✅ | ✅ | ⚠️ Fixed per step, no custom template |

---

## Runtime capabilities status

### Durability and replay
- ✅ **Checkpoint integration**: LangGraph SQLite checkpointer working
- ✅ **Thread-based execution**: `thread_id` used for replay context
- ✅ **Step idempotency**: Cached result retrieval on replay
- ✅ **Retry preparation**: Retry event + `last_node_id` resume
- ✅ **Checkpoint introspection**: API to list and inspect checkpoints
- ❌ **Selective checkpointing**: `is_checkpoint` flag not used

### Concurrency and safety
- ✅ **Resource leases**: Acquisition/release with expiry
- ✅ **Concurrency limits**: Per-agent `concurrency_limit` enforced
- ❌ **Stale lease cleanup**: No operator API to force-release
- ❌ **Workflow-level concurrency**: No dedupe windows or global limits

### Policy enforcement
- ✅ **Global retry policy**: `max_retries`, `retry_delay_ms` enforced with exponential backoff
- ❌ **Global timeout**: `timeout_ms` not enforced at workflow level
- ❌ **Node SLA monitoring**: `sla.max_duration_ms` not tracked
- ❌ **Rate limiting**: `rate_limiting.max_requests_per_minute` not enforced

### Observability
- ✅ **Event timeline**: Step/node/subflow/artifact events emitted
- ✅ **SSE stream**: Live event subscription working
- ✅ **Basic metrics**: In-memory counters for runs, steps, retries, duration
- ✅ **Metrics API**: `GET /api/runs/metrics/summary` endpoint
- ❌ **Metrics export**: No OpenTelemetry or Prometheus integration
- ❌ **Telemetry fields**: `telemetry.track_duration` not acted upon
- ❌ **Alert hooks**: No failure/stuck-run notifications

### Security and governance
- ✅ **Secrets**: Abstract provider with env vars & Vault support
- ✅ **Redaction**: Pattern-based redaction for sensitive fields in events/logs
- ❌ **AuthN/AuthZ**: No identity or role enforcement
- ✅ **Audit compliance**: Event redaction enforced, retention not implemented

---

## API completeness

| Endpoint | Implemented | Missing Features |
|----------|-------------|------------------|
| `POST /api/procedures` | ✅ | Trigger registration |
| `GET /api/procedures` | ✅ | Search by retrieval_metadata |
| `GET /api/procedures/{id}/{version}` | ✅ | Provenance details |
| `POST /api/runs` | ✅ | Dry-run mode, trigger context |
| `GET /api/runs` | ✅ | Advanced filtering (by SLA breach, telemetry) |
| `GET /api/runs/{id}` | ✅ | None |
| `GET /api/runs/{id}/events` | ✅ | Event filtering/grouping |
| `GET /api/runs/{id}/artifacts` | ✅ | Artifact metadata enrichment |
| `GET /api/runs/{id}/stream` | ✅ | None |
| `POST /api/runs/{id}/retry` | ✅ | Retry with policy override |
| `GET /api/runs/{id}/diagnostics` | ✅ | None |
| `GET /api/runs/{id}/checkpoints` | ✅ | None |
| `GET /api/runs/{id}/checkpoints/{checkpoint_id}` | ✅ | None |
| `GET /api/approvals` | ✅ | SLA/escalation indicators |
| `POST /api/approvals/{id}/decision` | ✅ | Role-based authorization check |
| `GET /api/agents` | ✅ | Agent health status |
| `GET /api/leases` | ❌ | **Not implemented** |
| `POST /api/leases/{id}/release` | ❌ | **Not implemented** |
| `POST /api/triggers` | ❌ | **Not implemented** |
| `GET /api/runs/metrics/summary` | ✅ | None |
| `GET /api/procedures/{id}/{version}/graph` | ✅ | None |

---

## Frontend completeness

| Feature | Implemented | Gap |
|---------|-------------|-----|
| Procedure listing | ✅ | Search by keywords/domain |
| Procedure version detail | ✅ | Provenance display |
| Procedure edit | ✅ | Inline validation |
| Run listing | ✅ | Advanced filters (SLA breach, retry count) |
| Run detail | ✅ | Diagnostics panel, checkpoint viewer |
| Run timeline | ✅ | Event filters, retry-path visualization |
| Artifact rendering | ✅ | Type-aware preview/download |
| Approval inbox | ✅ | SLA/escalation indicators |
| Agent listing | ✅ | Health status, concurrency usage |
| Workflow graph viewer | ✅ | Interactive React Flow with minimap, zoom, pan |
| Workflow editor | ❌ | **Not implemented** |
| Diagnostics console | ❌ | **Not implemented** |
| LLM/agent observability | ❌ | **Not implemented** |

---

## Testing and quality status

| Category | Coverage | Priority |
|----------|----------|----------|
| Backend unit tests | ~70% (157 tests) | Medium |
| Backend integration tests | ~20% (18 API tests) | Medium |
| Frontend unit tests | 0% | Medium |
| Frontend e2e tests | 0% | High |
| CI pipeline | None | Medium |
| Lint/format checks | Manual only | Low |
| Type coverage | High (TS/Python typing) | N/A |

---

## Quick win priorities (sorted by impact/effort)

### ✅ Completed (2026-02-17)
1. ~~**Add diagnostics API**~~ (`GET /api/runs/{id}/diagnostics`) — ✅ Implemented
2. ~~**Enforce global retry policy**~~ — ✅ Implemented with exponential backoff
3. ~~**Add event redaction for sensitive fields**~~ — ✅ Pattern-based redaction active
4. ~~**Add metrics export (basic counters)**~~ — ✅ In-memory metrics with API endpoint
5. ~~**Add checkpoint introspection API**~~ — ✅ List & inspect checkpoint history
6. ~~**Implement secrets provider integration**~~ — ✅ Abstract provider with env vars & Vault support

### ✅ Completed (2026-02-17, batch 2)
7. ~~**Add comprehensive backend tests**~~ — ✅ 157 tests: parser (26), validator (16), binder (7), redaction (21), metrics (17), secrets (11), graph (13), API (18), graph API (2)
8. ~~**Add workflow graph viewer (interactive)**~~ — ✅ Backend graph extraction endpoint + React Flow frontend with custom CKP nodes, minimap, zoom/pan, color-coded node types, agent badges

### 🔄 Remaining priorities
9. **Implement trigger scheduler** — High impact, high effort
10. **Add AuthN/AuthZ baseline** — High impact, high effort

---

## References

- Full roadmap: [FUTURE_PLAN.md](FUTURE_PLAN.md)
- CKP syntax: [ckp_file-main/ckp_file_syntex.txt](ckp_file-main/ckp_file_syntex.txt)
- Understanding doc: [UNDERSTANDING.md](UNDERSTANDING.md)
- Implementation spec: [IMPLEMENTATION_SPEC.md](IMPLEMENTATION_SPEC.md)
- Main README: [README.md](README.md)
