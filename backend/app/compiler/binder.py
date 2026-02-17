"""Binder — compile-time binding for IR steps.

Design:
  The binder does NOT hardcode channel→action or agent→channel mappings.
  Agents and tools are registered dynamically via the portal (DB).

  At compile time the binder can only:
    1. Tag obviously internal actions (log, wait, set_variable, etc.)
       — these never need an external agent.
    2. Leave everything else UNBOUND (executor_binding = None).

  At runtime, the executor dispatcher queries the agent registry (DB)
  to find a registered, online agent whose channel matches the CKP
  node's `agent` field and whose capabilities include the step's
  `action`.  This is done in runtime/executor_dispatch.py.

Why this matters:
  - Users register agents via the portal with channel + capabilities
  - The orchestrator should discover executors dynamically, not assume
    a fixed set of names/channels
  - New agents can be added without touching any code
"""

from __future__ import annotations

from app.compiler.ir import ExecutorBinding, IRProcedure, IRSequencePayload

# These actions are always handled internally by the orchestrator itself
# — they never require an external agent or MCP tool.
_INTERNAL_ACTIONS: set[str] = {
    "log", "wait", "set_variable", "calculate", "format_data",
    "parse_json", "parse_csv", "generate_id", "get_timestamp",
    "set_checkpoint", "restore_checkpoint", "screenshot",
}


def bind_executors(ir: IRProcedure) -> IRProcedure:
    """Tag internal actions at compile time.  Everything else stays unbound
    and will be resolved dynamically at runtime from the agent registry."""
    for node in ir.nodes.values():
        if isinstance(node.payload, IRSequencePayload):
            for step in node.payload.steps:
                if step.action in _INTERNAL_ACTIONS:
                    step.executor_binding = ExecutorBinding(
                        kind="internal", ref=step.action
                    )
                # else: executor_binding remains None → runtime resolves it
    return ir
