"""Binder â€” compile-time binding for IR steps.

Design:
  The binder does NOT hardcode channel->action or agent->channel mappings.
  Agents and tools are registered dynamically via the portal (DB).

  At compile time the binder can only:
    1. Tag obviously internal actions (log, wait, set_variable, etc.)
       because these never need an external agent.
    2. Leave everything else unbound (executor_binding = None).

  At runtime, the executor dispatcher queries the agent registry (DB)
  to find a registered, online agent whose channel matches the CKP
  node's `agent` field and whose capabilities include the step's
  `action`. This is done in runtime/executor_dispatch.py.
"""

from __future__ import annotations

from app.compiler.ir import ExecutorBinding, IRProcedure, IRSequencePayload
from app.contracts.action_contracts import INTERNAL_ACTIONS


def bind_executors(ir: IRProcedure) -> IRProcedure:
    """Tag internal actions at compile time and leave the rest dynamic."""
    for node in ir.nodes.values():
        if isinstance(node.payload, IRSequencePayload):
            for step in node.payload.steps:
                if step.action in INTERNAL_ACTIONS:
                    step.executor_binding = ExecutorBinding(
                        kind="internal",
                        ref=step.action,
                    )
    return ir
