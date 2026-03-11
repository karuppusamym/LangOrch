# Agent Swarm Integration in LangOrch

## Overview

LangOrch now includes a bounded agent swarm capability that lets you add multi-agent reasoning to workflows **without replacing the orchestrator**.

The key principle: **Use swarm as a brain, not an operating system.**

- **Swarm handles**: Planning, classification, risk assessment, specialist review, synthesis
- **LangOrch handles**: Durability, retries, approvals, resource leasing, audit, and execution

---

## What You Get

### 1. Design Document
[AGENT_SWARM_INTEGRATION_PROPOSAL.md](AGENT_SWARM_INTEGRATION_PROPOSAL.md)
- Explains the positioning and why bounded swarm makes sense for LangOrch
- Shows where swarm fits and where it doesn't
- Proposes a 3-phase rollout

### 2. Demo Agent
[backend/demo_agents/swarm_agent.py](backend/demo_agents/swarm_agent.py)
- HTTP FastAPI service implementing two swarm workflows:
  - `swarm.case_triage` — Classifies support tickets and recommends routing
  - `swarm.document_review` — Reviews documents for legal/security/commercial risk
- Registers automatically with the orchestrator
- Handles async delegation with callback-based resume

### 3. Sample CKP Procedure
[ckp_file-main/demo_case_triage_with_swarm.json](ckp_file-main/demo_case_triage_with_swarm.json)
- Shows how to call the swarm agent from a CKP workflow
- Demonstrates logic branching on swarm output
- Uses the existing async workflow capability contract

### 4. End-to-End Demo
[demo_procedures/run_swarm_demo.py](demo_procedures/run_swarm_demo.py)
- Runs 3 test cases through the swarm-enabled case triage workflow
- Shows full integration: deterministic data fetch → swarm reasoning → routing
- Displays structured swarm output and final results

### 5. Demo Guide
[demo_procedures/SWARM_DEMO_README.md](demo_procedures/SWARM_DEMO_README.md)
- Step-by-step instructions to run the demo
- Explains the workflow visually
- Shows test cases and expected results
- Includes troubleshooting and extension ideas

---

## Quick Start

### 1. Start Required Services

**Backend** (8000):
```powershell
cd c:\Users\karup\AGProjects\LangOrch\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

**Swarm Agent** (9006):
```powershell
cd c:\Users\karup\AGProjects\LangOrch\backend\demo_agents
powershell -ExecutionPolicy Bypass -File .\run_swarm_agent.ps1
```

**Frontend** (3000, optional):
```powershell
cd c:\Users\karup\AGProjects\LangOrch\frontend
npm run dev
```

### 2. Run the Demo

```powershell
cd c:\Users\karup\AGProjects\LangOrch
.\.venv\Scripts\python.exe demo_procedures/run_swarm_demo.py
```

This will:
1. Register the swarm agent
2. Import the demo CKP procedure
3. Create 3 test runs with different ticket types
4. Display swarm triage results (classification, routing decision, confidence)

### 3. View in UI (Optional)

Visit `http://localhost:3000/runs` to see:
- Full run timeline with swarm delegation and callback events
- Structured swarm output in run variables
- Specialist reports embedded in the result

---

## Architecture

```
┌─────────────────────────────────────────────────┐
│  LangOrch Orchestrator (Control Plane)           │
│  - CKP compilation + validation                  │
│  - Durable run state (checkpointing)             │
│  - Retry, approval, audit logic                  │
│  - Resource leasing + concurrency control        │
└──────────────────────┬──────────────────────────┘
                       │ Async delegation
                       │ (callback-based)
              ┌────────▼────────┐
              │ Swarm Agent     │
              │ (Reasoning)     │
              │ ┌────────────┐  │
              │ │ Planner    │  │
              │ │┌─────────┐ │  │
              │ ││Specialist│ │  │
              │ │└─────────┘ │  │
              │ │┌─────────┐ │  │
              │ ││Specialist│ │  │
              │ │└─────────┘ │  │
              │ │Synthesizer │  │
              │ └────────────┘  │
              └────────┬────────┘
                       │ Callback + structured output
                       │
              ┌────────▼───────────┐
              │ Logic branching    │
              │ (deterministic)    │
              └────────┬───────────┘
                       │
              ┌────────▼────────────────────┐
              │ Execution (WEB, DESKTOP,    │
              │ EMAIL, API, DB, LLM agents) │
              └─────────────────────────────┘
```

---

## Key Files Explained

| File | Purpose |
|---|---|
| [AGENT_SWARM_INTEGRATION_PROPOSAL.md](AGENT_SWARM_INTEGRATION_PROPOSAL.md) | **Read first**: Design rationale and positioning |
| [backend/demo_agents/swarm_agent.py](backend/demo_agents/swarm_agent.py) | Swarm agent implementation (FastAPI) |
| [backend/demo_agents/run_swarm_agent.ps1](backend/demo_agents/run_swarm_agent.ps1) | Launch script for swarm agent |
| [ckp_file-main/demo_case_triage_with_swarm.json](ckp_file-main/demo_case_triage_with_swarm.json) | Sample workflow using swarm |
| [demo_procedures/run_swarm_demo.py](demo_procedures/run_swarm_demo.py) | **Run this**: End-to-end demo script |
| [demo_procedures/SWARM_DEMO_README.md](demo_procedures/SWARM_DEMO_README.md) | Detailed guide for the demo |

---

## Use Cases

### Case Triage & Routing
Swarm classifies inbound support tickets, assesses urgency and risk, and recommends the right handler queue (finance, security, legal, etc.). LangOrch then routes deterministically.

### Document Review
Swarm specialists review contracts for legal, security, and commercial risk. Results are merged into an executive summary. LangOrch decides approval requirements based on risk level.

### Research & Enrichment
Swarm gathers facts, summarizes sources, and proposes recommendations. LangOrch then executes downstream actions (API calls, database updates, email notifications).

### Exception Analysis
When a workflow fails, swarm analyzes logs and artifacts to recommend retry, escalation, or manual review. LangOrch retains final control.

---

## Design Principles

1. **Bounded Reasoning**: Swarm has iteration limits, cost limits, and timeout constraints.

2. **Structured Output**: Swarm never returns free-form text—always a strict schema. This allows deterministic downstream routing.

3. **No Direct Mutation**: Swarm cannot directly modify system state. All mutations are deterministic steps in LangOrch.

4. **Centered Authority**: LangOrch remains the control plane. Swarm is a capability provider.

5. **Durable & Auditable**: Full event logs, retry semantics, and approval gates stay in LangOrch.

---

## Rollout Roadmap

**Phase 1 (Done)**: External swarm agent + existing workflow capability contract
- Swarm deployed as HTTP agent
- Reuses async delegation model
- Minimal orchestrator changes

**Phase 2 (Next)**: Enhanced observability
- Swarm-specific run events
- Planner + specialist trace capture
- Cost and iteration telemetry

**Phase 3 (Future)**: Productize
- New `planner` or `swarm` node type in CKP
- Visual builder support for bounded reasoning
- Governance policies (role constraints, output validation)

---

## Questions?

See [AGENT_SWARM_INTEGRATION_PROPOSAL.md](AGENT_SWARM_INTEGRATION_PROPOSAL.md) for detailed Q&A on design choices, risks, and mitigations.
