# Case Queue Demo: 10-Name Web Search

This demo shows how to use **LangOrch's case queue** to process multiple work items (10 person names) with the same procedure but different parameters.

## What It Demonstrates

✅ **Case-based work distribution** — Each name is a separate case  
✅ **Queue prioritization** — High-priority cases processed first  
✅ **Parameterization** — Same procedure, different inputs per case  
✅ **Multi-worker concurrency** — 2 workers claim and process in parallel  
✅ **Resource limits** — Only 2 browser sessions at a time  
✅ **SLA tracking** — Analytics show breach risk and wait times  
✅ **Audit trail** — Full history of who claimed what and when  

---

## Quick Start

### 1. Start the Backend

```powershell
cd backend
python -m uvicorn app.main:app --reload
```

Backend runs on `http://localhost:8000`

### 2. Start the Web Agent (Optional)

For dry-run mode (mock responses):
```powershell
cd backend/demo_agents
$env:WEB_AGENT_DRY_RUN="true"
python web_agent.py
```

For real browser mode:
```powershell
cd backend/demo_agents
$env:WEB_AGENT_DRY_RUN="false"
python web_agent.py
```

Web agent runs on `http://localhost:9000`

### 3. Run the Demo

```powershell
python demo_procedures/run_10_name_searches.py
```

---

## How It Works

### Architecture

```
┌─────────────────────────────────┐
│ 10 Cases (Names to Research)   │
│ - Alan Turing                   │
│ - Grace Hopper                  │
│ - Ada Lovelace                  │
│ - ... (7 more)                  │
└──────────┬──────────────────────┘
           │
           ↓
┌──────────────────────────────────┐
│ Priority Queue                   │
│ Sorted by:                       │
│ 1. SLA breach (expired first)    │
│ 2. Priority (high → normal)      │
│ 3. Age (FIFO within tier)        │
└──────────┬───────────────────────┘
           │
           ↓
┌──────────┴───────────┐
│                      │
▼                      ▼
Worker 01          Worker 02
(5 cases)          (5 cases)
    │                  │
    └─────────┬────────┘
              │
              ↓
┌─────────────────────────────────┐
│ Web Search Procedure (CKP)      │
│ 1. Navigate to Google            │
│ 2. Type: {{person_name}}         │
│ 3. Extract results               │
│ 4. Store in case metadata        │
└─────────────────────────────────┘
```

### Parameter Mapping

Each case has metadata that becomes procedure variables:

**Case Metadata:**
```json
{
  "person_name": "Alan Turing",
  "search_timeout_ms": 10000,
  "research_category": "computer_science"
}
```

**Run Initial State (from case metadata):**
```json
{
  "case_id": "case_abc123",
  "person_name": "Alan Turing",
  "search_timeout_ms": 10000
}
```

**CKP Template Expansion:**
```json
{
  "action": "type",
  "selector": "textarea[name='q']",
  "text": "{{person_name}} computer scientist"
}
```

Becomes → `"Alan Turing computer scientist"`

---

## Expected Output

```
============================================================
CASE QUEUE + WEB SEARCH DEMO
10 Names → Queue → Workers → Web Search → Results
============================================================

STEP 1: Create web search procedure
------------------------------------------------------------
✓ Created procedure: web_search_person_1709853820

STEP 2: Create 10 cases with different names
------------------------------------------------------------
✓ Created case 1/10: Alan Turing (high, 1h SLA)
✓ Created case 2/10: Grace Hopper (high, 1h SLA)
✓ Created case 3/10: Ada Lovelace (high, 1h SLA)
✓ Created case 4/10: Donald Knuth (normal, 24h SLA)
...

STEP 3: Queue state before processing
============================================================
QUEUE ANALYTICS
============================================================
Total active cases:     10
Unassigned:             10
SLA breached:           0
Breach risk (next 60m): 3
Wait time p50:          2.1s
Wait time p95:          2.3s
============================================================

STEP 4: Start 2 workers to process queue
------------------------------------------------------------

[worker_01] Claiming case: Alan Turing
[worker_02] Claiming case: Grace Hopper
[worker_01] Starting procedure for: Alan Turing
[worker_02] Starting procedure for: Grace Hopper
[worker_01] ✓ Run completed: Alan Turing (took 3.2s)
[worker_01] Released case: Alan Turing
[worker_02] ✓ Run completed: Grace Hopper (took 3.5s)
[worker_02] Released case: Grace Hopper

[worker_01] Claiming case: Ada Lovelace
[worker_02] Claiming case: Donald Knuth
...

[worker_01] Finished processing 5 cases
[worker_02] Finished processing 5 cases

STEP 5: Final results
============================================================
FINAL RESULTS
============================================================
 1. Alan Turing        | resolved     | Alan Turing - Wikipedia
 2. Grace Hopper       | resolved     | Grace Hopper - Computer Scientist
 3. Ada Lovelace       | resolved     | Ada Lovelace - Mathematician
 4. Donald Knuth       | resolved     | Donald Knuth - Stanford University
 5. Richard Stallman   | resolved     | Richard Stallman - Free Software
...
============================================================

✓ Demo complete!
```

---

## Key Patterns

### 1. Queue-Based Distribution

Workers pull from queue rather than push-based assignment:
```python
resp = await client.get("/api/cases/queue?only_unassigned=true&limit=1")
case = resp.json()[0]
```

### 2. Claim → Process → Release

```python
# Claim
await client.post(f"/api/cases/{case_id}/claim", 
                  json={"owner": "worker_01"})

# Process (run procedure)
run = await client.post("/api/runs", json={...})

# Release (always, even if error)
await client.post(f"/api/cases/{case_id}/release",
                  json={"owner": "worker_01"})
```

### 3. Resource Limits

CKP global config enforces concurrency:
```json
{
  "global_config": {
    "resource_leasing": {
      "resource_key": "web_browser",
      "concurrency_limit": 2
    }
  }
}
```

Only 2 browsers open at once, even with 10 workers.

---

## Comparison with UiPath

| Feature | LangOrch Cases | UiPath Queues |
|---------|---------------|---------------|
| Work items | Cases | Queue Items |
| Parameters | `case.metadata` | `QueueItem.SpecificContent` |
| Assignment | `claim_case()` | `Get Transaction Item` |
| Prioritization | SLA + priority + age | Priority only |
| SLA tracking | Built-in with analytics | Requires Orchestrator Enterprise |
| Concurrency | Resource leasing | Pool-based licensing |
| Audit trail | Case events (full history) | Transaction logs |

---

## Next Steps

1. **Add approvals**: Insert `human_approval` node for high-value cases
2. **Add LLM decision**: Use `llm_action` to classify results before storing
3. **Scale workers**: Run 10 workers across 3 machines (resource limit still enforced)
4. **Add retries**: Failed cases stay in queue, workers retry automatically
5. **Monitor SLA**: Set up alerts when `breach_risk_next_window_percent > 50%`

---

## Troubleshooting

**Backend not starting:**
```powershell
cd backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app
```

**Web agent 404:**
```powershell
cd backend/demo_agents
python web_agent.py
```

**No cases processed:**
- Check web_agent is registered: `GET /api/agents`
- Check procedure was created: `GET /api/procedures`
- Check cases exist: `GET /api/cases`

**Slow execution:**
- Use dry-run mode: `$env:WEB_AGENT_DRY_RUN="true"`
- Reduce timeout: Change `search_timeout_ms` to 5000
