# LangOrch Agent Swarm Integration Proposal

## Purpose

This document explains how "agent swarm" patterns should be applied to LangOrch without weakening the platform's core value: deterministic, durable, orchestrator-first execution.

The recommendation is simple:

- Keep LangOrch as the control plane and execution authority.
- Use swarm-style multi-agent reasoning only for bounded cognitive tasks.
- Keep deterministic actions, leases, approvals, retries, and audit trails in LangOrch.

## What "Agent Swarm" Means Here

For this repository, an agent swarm should mean a bounded set of cooperating specialist agents that work on a single reasoning problem and return structured output.

Typical swarm roles:

- Planner: decomposes a goal into sub-tasks.
- Router: decides which specialists should be used.
- Specialists: perform domain-specific reasoning such as legal review, risk assessment, extraction, or summarization.
- Synthesizer: merges specialist outputs into one normalized result.
- Critic or verifier: checks whether the result meets required constraints.

This is useful for ambiguity-heavy work. It is not the right primary model for browser clicks, desktop automation, queue handling, or strict operational sequencing.

## Why LangOrch Is Already Close

LangOrch already provides most of the infrastructure needed to host bounded swarm execution safely:

- Registered agents with declared capabilities.
- Distinction between granular tool calls and delegated workflow execution.
- Async workflow delegation with pause and callback resume.
- Parallel branches in CKP.
- Resource-key leasing and concurrency control.
- Durable run state, retries, approvals, artifacts, and event timelines.

Because of that, the platform does not need a separate swarm runtime as the top-level product. It needs a swarm-capable agent type inside the existing runtime.

## Recommended Positioning

Use swarm for the "thinking" layer.

Use LangOrch for the "doing" layer.

That means:

- Swarm handles interpretation, planning, classification, comparison, synthesis, and recommendation.
- LangOrch handles execution of API calls, web steps, desktop steps, queue routing, human approvals, retries, and replay.

## Where Swarm Fits Best

### 1. Case Intake and Triage

Input:

- customer message
- attachments
- account metadata
- channel context

Swarm output:

- issue_type
- urgency
- extracted_entities
- recommended_route
- confidence
- explanation

LangOrch then uses that structured result to route the case into a deterministic CKP path.

### 2. Research and Enrichment

Input:

- a company, person, or document set
- business objective
- guardrails and data sources

Swarm output:

- normalized findings
- evidence list
- risk flags
- recommended next action

LangOrch then executes downstream steps such as CRM update, email draft generation, approval routing, or API submission.

### 3. Exception Analysis

Input:

- failed run timeline
- artifacts
- error payloads
- prior retry history

Swarm output:

- probable root cause
- safe retry recommendation
- escalation recommendation
- required human context

LangOrch still owns the actual retry or escalation decision path.

### 4. Specialist Review

This repo already models a close variant of swarm behavior through parallel specialist analysis. A true swarm version would make the specialist set dynamic rather than hard-coded, while still returning a structured review packet.

## Where Swarm Should Not Be In Charge

Do not let a free-form swarm directly own:

- browser or desktop action sequences
- capacity allocation
- resource leasing
- queue claims and work distribution
- approval state transitions
- timeout, retry, or replay semantics
- final mutation of system-of-record data without deterministic checks

Those responsibilities already belong to LangOrch and should stay there.

## Integration Model

There are two good ways to add swarm behavior to LangOrch.

### Option A. Swarm as a Workflow Capability Agent

Create a new HTTP agent that registers one or more capabilities such as:

- `swarm.case_triage`
- `swarm.document_review`
- `swarm.failure_analysis`

Each capability is declared as type `workflow`.

Why this fits well:

- long-running cognition can run asynchronously
- existing callback pause and resume behavior already exists
- swarm execution stays isolated from the orchestrator core
- outputs can be merged into run variables like any other delegated workflow result

Recommended when:

- execution may take more than a few seconds
- you want planner and specialist traces bundled in one external component
- you want easy model or framework substitution later

### Option B. Swarm as a New Planner-Like Node Type

Introduce a bounded node type such as `planner` or `cognitive_workflow` in CKP.

The node declares:

- goal
- allowed tools or specialist roles
- max iterations
- max cost
- output schema
- failure policy

Why this fits well:

- planner intent becomes a first-class workflow primitive
- users can see swarm boundaries directly in the builder
- policy can be validated at compile time

Recommended when:

- LangOrch wants planner behavior to become a core product feature
- governance and visualization in the builder matter more than framework flexibility

## Recommended First Implementation

Start with Option A.

Rationale:

- It reuses the existing workflow capability contract.
- It avoids immediate compiler and builder changes.
- It lets the swarm implementation iterate independently.
- It is lower-risk than adding a new node type first.

After the contract is proven, Option B can become the productized abstraction.

## Execution Contract for a Swarm Agent

The swarm agent should never return unbounded natural-language-only output. It should always return a strict envelope with structured fields.

Suggested request shape:

```json
{
  "action": "swarm.case_triage",
  "params": {
    "goal": "Classify the case and recommend a route",
    "context": {
      "ticket_text": "...",
      "customer_tier": "enterprise",
      "channel": "email"
    },
    "constraints": {
      "max_iterations": 6,
      "max_cost_usd": 0.75,
      "allowed_roles": ["classifier", "risk_reviewer", "router"]
    },
    "output_schema": {
      "issue_type": "string",
      "urgency": "low|medium|high",
      "recommended_route": "string",
      "confidence": "number"
    },
    "callback_url": "https://.../api/runs/{run_id}/callback"
  },
  "run_id": "...",
  "node_id": "...",
  "step_id": "..."
}
```

Suggested callback output:

```json
{
  "status": "success",
  "output": {
    "swarm_result": {
      "issue_type": "billing_dispute",
      "urgency": "high",
      "recommended_route": "finance_specialist_queue",
      "confidence": 0.91,
      "explanation": "Customer reports failed renewal charge and contract mismatch.",
      "specialist_reports": [
        {"role": "classifier", "summary": "..."},
        {"role": "risk_reviewer", "summary": "..."},
        {"role": "router", "summary": "..."}
      ]
    }
  },
  "node_id": "...",
  "step_id": "..."
}
```

## Hard Requirements

Any swarm integration should obey these rules:

- Bounded iterations only.
- Explicit cost limit.
- Structured output schema.
- Deterministic failure mode when schema validation fails.
- Full trace capture of planner decisions and specialist outputs.
- No direct mutation of external systems from inside the swarm unless specifically wrapped as deterministic tool calls.
- Optional human approval before irreversible actions.

## Minimal CKP Pattern

The first usable CKP pattern can remain simple:

1. Deterministic data collection steps.
2. Delegate one swarm workflow step.
3. Resume with logic branch based on structured swarm output.
4. Continue with deterministic actions.

Illustrative shape:

```json
{
  "id": "case_intake_with_swarm",
  "nodes": [
    {
      "id": "collect_context",
      "type": "sequence",
      "steps": [
        {"action": "ticket.fetch"},
        {"action": "customer.lookup"}
      ]
    },
    {
      "id": "triage_swarm",
      "type": "sequence",
      "steps": [
        {
          "action": "swarm.case_triage",
          "agent": "hybrid_or_swarm_pool",
          "workflow_dispatch_mode": "async",
          "params": {
            "goal": "Classify and route this case",
            "context": {
              "ticket_text": "{{variables.ticket.body}}",
              "customer": "{{variables.customer}}"
            }
          }
        }
      ]
    },
    {
      "id": "route_case",
      "type": "logic",
      "condition": "{{variables.swarm_result.recommended_route}} == 'finance_specialist_queue'"
    }
  ]
}
```

## Observability Additions

To make swarm execution operationally useful, LangOrch should capture these event types:

- `swarm_planning_started`
- `swarm_specialist_invoked`
- `swarm_specialist_completed`
- `swarm_synthesis_completed`
- `swarm_schema_validated`
- `swarm_guardrail_violation`

It should also expose a compact swarm trace in run detail views.

## Builder and UX Implications

Near term:

- represent swarm use as a workflow-capability step
- add a small UI affordance showing that the step is delegated cognitive work

Later:

- add a dedicated planner or swarm node in the builder
- allow role selection, iteration limit, and output schema editing
- visualize specialist fan-out and synthesis in run traces

## Risks

### Risk 1. Unbounded agent loops

Mitigation:

- max iterations
- max elapsed time
- max cost

### Risk 2. Non-deterministic outputs breaking downstream nodes

Mitigation:

- strict schema validation
- versioned output contracts
- fallback branch for invalid output

### Risk 3. Swarm bypasses governance

Mitigation:

- approvals remain in LangOrch
- swarm cannot finalize irreversible actions without orchestrator approval path

### Risk 4. Debuggability becomes poor

Mitigation:

- trace each specialist output
- persist final rationale and evidence list
- keep event timeline aligned with run state

## Suggested Phased Rollout

### Phase 1. External Swarm Agent

- build one HTTP swarm agent
- register one workflow capability such as `swarm.case_triage`
- use existing async workflow delegation
- return validated structured output only

### Phase 2. Trace and Policy Enhancements

- add swarm-specific run events
- store planner and specialist summaries as artifacts or structured timeline payloads
- enforce cost and iteration guardrails centrally

### Phase 3. Productize in CKP and Builder

- introduce `planner` or `swarm` node type
- add compiler validation for role policies and output schemas
- add builder UX for bounded agentic workflows

## Bottom Line

Agent swarm is applicable to LangOrch, but only as a bounded reasoning subsystem.

The correct architecture is not:

- swarm everywhere

The correct architecture is:

- LangOrch orchestrates
- swarm reasons
- deterministic agents execute
- LangOrch records, governs, and resumes

That preserves the differentiator of this platform while adding higher-value AI behavior where it actually helps.