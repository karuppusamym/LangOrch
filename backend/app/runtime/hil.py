"""Human-in-the-loop helpers — interrupt/resume integration with LangGraph."""

from __future__ import annotations

from typing import Any

from app.compiler.ir import IRHumanApprovalPayload, IRNode
from app.runtime.state import OrchestratorState


def build_approval_interrupt_payload(node: IRNode, state: OrchestratorState) -> dict[str, Any]:
    """Build the payload that will be passed to LangGraph's interrupt()."""
    payload: IRHumanApprovalPayload = node.payload
    return {
        "node_id": node.node_id,
        "prompt": payload.prompt,
        "decision_type": payload.decision_type,
        "options": payload.options,
        "context_data": payload.context_data,
        "approval_level": payload.approval_level,
        "timeout_ms": payload.timeout_ms,
    }


def resolve_approval_next_node(
    node: IRNode, decision: str
) -> str | None:
    """Given an approval decision, return the next_node_id to route to."""
    payload: IRHumanApprovalPayload = node.payload
    mapping = {
        "approved": payload.on_approve,
        "approve": payload.on_approve,
        "rejected": payload.on_reject,
        "reject": payload.on_reject,
        "timed_out": payload.on_timeout,
        "timeout": payload.on_timeout,
    }
    return mapping.get(decision, payload.on_reject)
