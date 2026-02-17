# LangOrch — Understanding Document (Orchestrator-first)

## 1. What this repository is building
This workspace is aiming to build an **Agentic Automation Platform** where the **Orchestrator** is the product.

- **CKP (Canonical Knowledge Procedure)** JSON is the canonical workflow definition format.
- The Orchestrator loads CKP, validates it, compiles it into an internal execution plan (IR), and executes it durably.
- “Agents” (WEB/DESKTOP/EMAIL/API/DATABASE/LLM/etc.) are execution workers.
- **LangGraph is the runtime engine** used inside the Orchestrator to get durable execution patterns (checkpointing + resume + human-in-the-loop), not a replacement for the entire control plane.

Observer/O2A (capture → generate CKP) is explicitly deferred; orchestration is the current focus.

## 2. Core requirements captured in readme-understanding
### 2.1 Orchestrator layer (core)
The Orchestrator must:
- Interpret workflow JSON (CKP)
- Execute nodes in order, including branching + loops
- Call tools via MCP and call agents via HTTP/stdio/OpenAPI
- Manage state + variables across steps/agents
- Coordinate subflows
- Support human-in-the-loop (pause/approve/resume)
- Support retries, reruns, resume-from-crash
- Persist execution history; maintain traces/logs
- Support event-driven execution

The Orchestrator must be:
- Durable, replayable, observable, extensible, multi-agent capable

### 2.2 Human-in-the-loop (critical)
- Approval gates in UI/API
- Manual overrides and editable inputs
- Step pause/resume
- Full audit trail

### 2.3 Persistence / replay
- Run-level and step-level persistence
- Idempotency + retry tracking
- Deterministic-ish replay and historical comparisons

## 3. CKP is the canonical workflow contract
The CKP shape is described by:
- Syntax reference: [ckp_file-main/ckp_file_syntex.txt](ckp_file-main/ckp_file_syntex.txt)
- Example: [ckp_file-main/sample_workflow_multi_agent.json](ckp_file-main/sample_workflow_multi_agent.json)

### 3.1 Top-level fields (procedure)
Based on the syntax reference + sample:
- `procedure_id`, `version`, `status`, `effective_date`, `description`
- `trigger`: manual/scheduled/webhook/event/file_watch
- `retrieval_metadata`: intents, domain, keywords
- `global_config`: retries, timeouts, checkpointing strategy/storage, resume policy, telemetry, secrets, audit
- `variables_schema`: required/optional variables, types, validation, sensitivity
- `workflow_graph`: `start_node` + `nodes` map
- `provenance`: compiler version + sources

### 3.2 Node model (workflow_graph.nodes[node_id])
Nodes have:
- `type`: sequence | logic | loop | parallel | processing | verification | llm_action | human_approval | transform | subflow | terminate | …
- `agent`: MasterAgent | WEB | DESKTOP | EMAIL | API | DATABASE | LLMAgent | …
- `inputs` / `outputs` (optional mapping into state)
- Transitions: `next_node`, `default_next_node`, `body_node`, `branches`, etc.
- Optional policies: `is_checkpoint`, `sla`, `telemetry`, `idempotency_key`

### 3.3 Steps + action catalog
A `sequence` node typically contains `steps[]`. Each step includes:
- `action` (from `action_catalog`)
- optional targeting fields: `target`, `url`, `title`, etc.
- optional value fields: `value`, `keys`, `parameters`, `query`, etc.
- timing: `timeout_ms`, `wait_ms`, `wait_after_ms`
- `output_variable` to store results into state

Actions are grouped by channel in the syntax reference (`generic`, `desktop`, `web`, `email`, `api`, `database`, `file`).

## 4. Key design decision: compile/bind vs runtime execution
The Orchestrator should do the work in **two phases**:

### 4.1 Compile/Bind phase (deterministic)
Inputs: CKP JSON + registries (agents/tools/policies)
Outputs: an internal plan (IR) where every node/step is *bound* to:
- which executor type (MCP tool call vs agent call vs pure transform)
- which concrete target (tool name, server, transport; agent endpoint)
- policies (retry/timeout/idempotency/checkpoint)

This phase performs static checks:
- graph validity (missing nodes, bad references)
- required variables available (from variables_schema)
- step actions supported (against action_catalog + agent/tool registry)

### 4.2 Run phase (dynamic only where CKP allows)
During execution, dynamic decisions are limited to what CKP expresses:
- `logic` rules
- `loop` iteration
- `verification` checks
- `human_approval` decisions
- `llm_action` outputs

This keeps the system “predictable” while still supporting dynamic branching.

## 5. LangGraph’s role in this architecture
LangGraph provides the **durable execution primitives** the Orchestrator needs:
- Checkpointing of state tied to a `thread_id` (resume/retry/replay)
- Human-in-the-loop patterns via interrupts (pause and later resume)
- A structured state machine / graph execution model

Important constraint: **side effects must be replay-safe**.
- Any external call (MCP tool, agent HTTP call, email send, DB write, LLM request) must be wrapped so replays don’t repeat the side effect unintentionally.
- The Orchestrator should treat external calls as “tasks” whose results are recorded and re-used on replay.

## 6. Concrete CKP → runtime mapping (what the Orchestrator must implement)
### 6.1 State model
Maintain a single run state object (LangGraph state) that includes:
- workflow variables (required + optional)
- secrets references (resolved at runtime via configured provider)
- current node + current step context
- error context (`error.message`, `error.node_id`, etc.)
- telemetry counters
- artifacts references (screenshots, downloaded files)

Templating uses `{{var}}` placeholders inside CKP strings.

### 6.2 Node semantics
Using the CKP types shown in the syntax reference + sample:

- `sequence`:
  - execute steps in order
  - after each step, merge outputs into state
  - apply node-level validations and error_handlers

- `logic`:
  - evaluate rules in order
  - route to the first matching `next_node`
  - otherwise go to `default_next_node`

- `loop`:
  - read `iterator` array from state
  - set `iterator_variable` (and optional `index_variable`)
  - run `body_node` repeatedly
  - optionally accumulate into `collect_variable`
  - honor `max_iterations`, `continue_on_error`, `next_node`

- `verification`:
  - evaluate checks and route/fail/warn based on `on_fail`

- `llm_action`:
  - call an LLM (must be treated as a side effect)
  - map outputs using `output_mapping` expressions (e.g., `json_extract: ...`)

- `human_approval`:
  - pause execution and persist checkpoint
  - resume using decision payload and route via `on_approve` / `on_reject` / `on_timeout`

- `transform` / `processing`:
  - pure operations on state (filter/map/aggregate, parse_json/csv, etc.)
  - should remain deterministic unless explicitly calling external resources

- `subflow`:
  - load referenced `procedure_id` and compile child CKP
  - map inputs/outputs as declared

- `terminate`:
  - mark run status (success/failed)
  - emit final outputs + audit record

### 6.3 Error handling and failure routing
CKP supports:
- Node `error_handlers` with retry policies, recovery steps, and fallback nodes
- Global `global_config.on_failure` node

The Orchestrator should normalize errors into a consistent error object in state so templates like `{{error.message}}` work.

## 7. Agent model and “step vs batch” execution
A key open design requirement from readme-understanding:
- “An agent can run a single step or multiple steps depending on design”

This should be solved by an **Agent Capability Contract** in the agent registry:
- `supported_actions`
- `execution_mode`: `step` | `batch` | `node`
- constraints: max steps per batch, max duration, session requirements

Binding rule:
- If the selected agent supports `batch`, the compiler may group adjacent compatible steps.
- Even with batching, the Orchestrator should retain step-level outcomes in the recorded result to support debug/replay and partial resume.

## 7b. Multi-run concurrency (desktop/web agents) and resource locking
When multiple runs execute at the same time, the orchestrator must prevent agent collisions.

### Desktop agent
- Desktop UI automation is typically **single-capacity per interactive session**.
- Two runs driving the same desktop session will fight for focus/keyboard/mouse and corrupt state.

Design: model each desktop automation environment as a separate **agent instance** with:
- `resource_key` (example: `desktop:vm-01:session-1`)
- `concurrency_limit` (usually 1)

The orchestrator must **acquire a lease/lock** on the resource_key before dispatching work. If the lock is held, the run waits (queues) instead of executing concurrently.

### Web agent
- Web automation can be concurrent if implemented with isolated contexts/workers.
- Still needs capacity limits (CPU/memory/site rate limits).

Design: model web capacity as agent instances too (example resource_key: `web:pool-a`) with a concurrency_limit > 1.

### How this interacts with CKP parallel
- CKP can express parallel branches.
- True parallelism happens only when branches use different available resources.
- If both branches require the same desktop resource_key, execution safely serializes due to the lock.

## 8. Minimal platform components (orchestrator-first)
Even with LangGraph, the Orchestrator still needs a platform control plane.

### 8.1 Registries
- Procedure registry: stores versioned CKP JSON
- Agent registry: capabilities + endpoints + auth
- Tool registry: MCP servers + tool schema + mapping from CKP action → tool

### 8.2 Run management
- Create run (`run_id`) and a durable `thread_id` (recommended: `thread_id == run_id`)
- Start / pause / resume / cancel / retry
- Event stream (timeline) for UI and audit

### 8.3 Persistence
Two layers:
- LangGraph checkpointer store: the durable state snapshots keyed by `thread_id`
- Platform DB tables: run index + run events + approvals + artifacts + audit

## 9. What the sample workflow demonstrates (why it matters)
The sample CKP file shows end-to-end multi-agent orchestration patterns:
- Email agent: search + download attachments
- Processing: parse data, log
- Logic gate: approval vs loop
- HITL: `human_approval` with escalation and timeout behavior
- Loop: iterate invoices and run a WEB→LLM→DESKTOP→DATABASE→EMAIL chain per item
- Termination: explicit success/failure nodes and global on-failure routing

See [ckp_file-main/sample_workflow_multi_agent.json](ckp_file-main/sample_workflow_multi_agent.json) for the concrete fields and patterns.

## 10. Known ambiguities / items to confirm later
These are not blockers for writing the Orchestrator, but should be decided early:
- Expression language: CKP uses `{{ ... }}` expressions (e.g., `{{invoice_list.length}} > 10`). Define a safe evaluator (not `eval`).
- Secrets resolution: standardize how `{{secrets.*}}` is populated from the configured provider.
- Parallel node semantics: whether to use true concurrency, cooperative scheduling, or queue-backed workers.
- Exactly-once vs at-least-once expectations for side effects: define idempotency keys and safe retries per action.

---

If you want, the next deliverable after this Understanding doc is a concrete “Implementation Spec” that lists:
- required API endpoints
- DB schema (tables + indexes)
- the IR structures for compiled CKP
- the exact mapping functions for each CKP node type
- the replay-safety wrapper contract for MCP and agent calls
