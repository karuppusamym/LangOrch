"""CKP static validator — checks IR integrity before execution."""

from __future__ import annotations

from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRParallelPayload,
    IRProcedure,
    IRSubflowPayload,
)


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__(f"CKP validation failed: {errors}")


def validate_ir(ir: IRProcedure) -> list[str]:
    """Return a list of error strings. Empty list means valid."""
    errors: list[str] = []

    if not ir.procedure_id:
        errors.append("Missing procedure_id.")
    if not ir.version:
        errors.append("Missing version.")
    if not ir.start_node_id:
        errors.append("Missing workflow_graph.start_node.")
    if ir.start_node_id and ir.start_node_id not in ir.nodes:
        errors.append(f"start_node '{ir.start_node_id}' does not exist in nodes.")

    all_node_ids = set(ir.nodes.keys())

    for nid, node in ir.nodes.items():
        # Check next_node references
        if node.next_node_id and node.next_node_id not in all_node_ids:
            errors.append(f"Node '{nid}': next_node '{node.next_node_id}' not found.")

        # Type-specific edge checks
        payload = node.payload

        if isinstance(payload, IRLogicPayload):
            for rule in payload.rules:
                if rule.next_node_id not in all_node_ids:
                    errors.append(f"Node '{nid}': logic rule target '{rule.next_node_id}' not found.")
            if payload.default_next_node_id and payload.default_next_node_id not in all_node_ids:
                errors.append(f"Node '{nid}': default_next_node '{payload.default_next_node_id}' not found.")

        elif isinstance(payload, IRLoopPayload):
            if payload.body_node_id and payload.body_node_id not in all_node_ids:
                errors.append(f"Node '{nid}': loop body_node '{payload.body_node_id}' not found.")
            if payload.next_node_id and payload.next_node_id not in all_node_ids:
                errors.append(f"Node '{nid}': loop next_node '{payload.next_node_id}' not found.")

        elif isinstance(payload, IRParallelPayload):
            for branch in payload.branches:
                if branch.start_node_id not in all_node_ids:
                    errors.append(f"Node '{nid}': parallel branch '{branch.branch_id}' start_node not found.")

        elif isinstance(payload, IRHumanApprovalPayload):
            for attr in ("on_approve", "on_reject", "on_timeout"):
                target = getattr(payload, attr, None)
                if target and target not in all_node_ids:
                    errors.append(f"Node '{nid}': {attr} '{target}' not found.")

        elif isinstance(payload, IRSubflowPayload):
            if payload.next_node_id and payload.next_node_id not in all_node_ids:
                errors.append(f"Node '{nid}': subflow next_node '{payload.next_node_id}' not found.")

    return errors
