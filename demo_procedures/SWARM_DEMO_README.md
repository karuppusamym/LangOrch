# Swarm Agent Demo Guide

This directory contains demonstration procedures and scripts. The **Swarm Agent Demo** shows how bounded multi-agent reasoning integrates into LangOrch without replacing the orchestrator.

---

## Quick Start: Run the Swarm Demo

The demo demonstrates:
- A planner+specialist swarm that classifies and routes support cases
- Async delegation to the swarm agent with callback resume
- Deterministic routing logic based on swarm output
- Full LangOrch durability, event tracking, and approval gates

### Prerequisites

1. **Backend running**: 
   ```powershell
   cd c:\Users\karup\AGProjects\LangOrch\backend
   .\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

2. **Swarm agent running**:
   ```powershell
   cd c:\Users\karup\AGProjects\LangOrch\backend\demo_agents
   powershell -ExecutionPolicy Bypass -File .\run_swarm_agent.ps1
   ```

3. **Frontend running** (optional, for UI viewing):
   ```powershell
   cd c:\Users\karup\AGProjects\LangOrch\frontend
   npm run dev
   ```

### Run the Demo

Once all three services are ready, execute:

```powershell
cd c:\Users\karup\AGProjects\LangOrch
.\.venv\Scripts\python.exe demo_procedures/run_swarm_demo.py
```

The script will:
1. Verify backend + swarm agent health
2. Register the swarm agent
3. Import the demo CKP procedure
4. Create 3 test runs with different ticket types
5. Wait for all runs to complete
6. Display swarm triage results (issue type, urgency, recommended route, confidence)

### View Results

After the script completes:

1. **In the terminal output**: See a summary of each run's swarm classification result.

2. **In the UI** (http://localhost:3000):
   - Go to **Runs** and select one of the demo runs
   - View the **Timeline** to see:
     - `collect_context` step (deterministic data fetch)
     - `workflow_delegated` event (swarm dispatched asynchronously)
     - `workflow_callback_received` event (swarm completed and posted result)
     - `route_case` step (LangOrch logic gate based on swarm output)
     - Terminal notification step
   - View **Variables** to see the structured `swarm_result`

---

## What the Demo Shows

### Case Triage Workflow

```
┌─────────────────────────────────────────────────┐
│ Collect: Fetch ticket and customer context     │ (Deterministic)
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ Swarm Triage: Async delegation                 │ (Bounded reasoning)
│  Planner: decompose goal                        │
│  Classifier: identify issue type                │
│  Risk Reviewer: assess risk flags               │
│  Router: recommend handler queue                │
│              ↓                                  │
│         [callback]                              │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ Route: Logic gate based on swarm output         │ (Deterministic)
│  - Billing → Finance queue                      │
│  - Security → Incident queue                    │
│  - Legal → Legal queue                          │
│  - Default → Support queue                      │
└──────────────┬──────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────┐
│ Notify: Send to appropriate handler             │ (Deterministic)
└─────────────────────────────────────────────────┘
```

### Test Cases

The demo creates 3 test tickets:

1. **Billing dispute**: Triggers `issue_type=billing`, routes to `finance_specialist_queue`
2. **Security incident**: Triggers `issue_type=security_incident`, `urgency=high`, routes to `security_incident_queue`
3. **Legal review**: Triggers `issue_type=contract_review`, routes to `legal_review_queue`

---

## Key Design Patterns

### 1. Swarm as Workflow Capability
The swarm agent is registered as a normal agent with workflow-type capabilities:
- `swarm.case_triage`
- `swarm.document_review`

This reuses the existing async delegation contract:
- Orchestrator fires the agent with `callback_url`
- Swarm runs independently and POSTs result when done
- Run pauses and resumes when callback arrives

### 2. Bounded Output Schema
Swarm never returns free-form text. It always returns:
```json
{
  "swarm_result": {
    "issue_type": "string",
    "urgency": "low|medium|high",
    "recommended_route": "string",
    "confidence": number,
    "risk_flags": ["flag1", "flag2"],
    "specialist_reports": [
      {"role": "classifier", "summary": "..."},
      {"role": "risk_reviewer", "summary": "..."}
    ]
  }
}
```

This allows the orchestrator to route deterministically without further LLM calls.

### 3. Orchestrator Retains Control
- Swarm cannot finalize actions or mutate system state
- All downstream operations (notification, escalation, approval) stay in LangOrch
- Governance, retries, human approval, and audit remain centralized

---

## Files in This Demo

| File | Purpose |
|---|---|
| `run_swarm_demo.py` | Main demo script; creates test runs and waits for completion |
| `../backend/demo_agents/swarm_agent.py` | The swarm agent HTTP service |
| `../backend/demo_agents/run_swarm_agent.ps1` | Launcher for the swarm agent |
| `../ckp_file-main/demo_case_triage_with_swarm.json` | The CKP procedure definition |
| `../AGENT_SWARM_INTEGRATION_PROPOSAL.md` | Design doc explaining swarm positioning in LangOrch |

---

## Extending the Demo

To use the swarm agent in your own procedures:

1. **Register the agent** (done automatically by the demo script):
   ```python
   POST /api/agents
   {
     "agent_id": "swarm-demo-agent",
     "name": "Bounded Swarm Demo Agent",
     "channel": "swarm",
     "base_url": "http://127.0.0.1:9006",
     "concurrency_limit": 2,
     "capabilities": [
       {"name": "swarm.case_triage", "type": "workflow"},
       ...
     ]
   }
   ```

2. **Add a swarm step to your CKP**:
   ```json
   {
     "id": "my_triage_step",
     "type": "sequence",
     "steps": [
       {
         "action": "swarm.case_triage",
         "agent": "swarm-demo-agent",
         "workflow_dispatch_mode": "async",
         "params": {
           "goal": "Classify this case",
           "context": {
             "ticket": "{{variables.input_ticket}}"
           }
         }
       }
     ]
   }
   ```

3. **Branch on the result**:
   ```json
   {
     "id": "route",
     "type": "logic",
     "branches": [
       {
         "condition": "{{variables.swarm_result.recommended_route}} == 'escalation'",
         "next": "escalate_node"
       }
     ]
   }
   ```

---

## Troubleshooting

**"Swarm agent health check failed. Is it running?"**
- Ensure `run_swarm_agent.ps1` is executing on port 9006
- Check: `curl http://127.0.0.1:9006/health`

**"Run did not complete within 120s"**
- Check backend logs for workflow delegation errors
- Verify swarm agent is responsive: `curl http://127.0.0.1:9006/health`
- Increase timeout in `run_swarm_demo.py` if needed

**"No swarm_result in run variables"**
- Check the run timeline for `workflow_delegated` and `workflow_callback_received` events
- If `workflow_delegated` is missing, the agent dispatch failed (check backend logs)
- If callback is missing, the swarm agent crashed or did not POST to the callback URL

---

## Next Steps

After running this demo:

1. **Add more swarm capabilities**: Extend `swarm_agent.py` with `swarm.document_review`, `swarm.failure_analysis`, etc.

2. **Productize in the builder**: Create a dedicated `planner` or `swarm` node type in the CKP compiler and visual builder.

3. **Add swarm-specific events**: Emit `swarm_planning_started`, `swarm_specialist_invoked`, `swarm_synthesis_completed` for better observability.

4. **Integrate with approval gates**: Add optional human approval before acting on swarm recommendations.

See [AGENT_SWARM_INTEGRATION_PROPOSAL.md](../AGENT_SWARM_INTEGRATION_PROPOSAL.md) for the full design rationale.
