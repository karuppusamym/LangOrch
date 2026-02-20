"""CKP static validator — checks IR integrity before execution."""

from __future__ import annotations

from collections import deque

from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRParallelPayload,
    IRProcedure,
    IRSubflowPayload,
)

_VALID_TRIGGER_TYPES = frozenset({"manual", "scheduled", "webhook", "event", "file_watch"})


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

    # ── Trigger validation ──────────────────────────────────────
    if ir.trigger and ir.trigger.type not in _VALID_TRIGGER_TYPES:
        errors.append(
            f"trigger.type '{ir.trigger.type}' is invalid. Must be one of: {sorted(_VALID_TRIGGER_TYPES)}."
        )
    if ir.trigger and ir.trigger.type == "scheduled" and not ir.trigger.schedule:
        errors.append("trigger.type 'scheduled' requires a 'schedule' (cron expression).")
    if ir.trigger and ir.trigger.type == "webhook" and not ir.trigger.webhook_secret:
        errors.append("trigger.type 'webhook' requires 'webhook_secret' for HMAC verification.")

    # ── Unreachable node detection ──────────────────────────────
    if ir.start_node_id and ir.start_node_id in all_node_ids:
        reachable: set[str] = set()
        queue: deque[str] = deque([ir.start_node_id])
        while queue:
            current = queue.popleft()
            if current in reachable:
                continue
            reachable.add(current)
            node = ir.nodes.get(current)
            if not node:
                continue
            # Collect all outgoing edges from this node
            edges: list[str] = []
            if node.next_node_id:
                edges.append(node.next_node_id)
            p = node.payload
            if isinstance(p, IRLogicPayload):
                edges.extend(r.next_node_id for r in p.rules)
                if p.default_next_node_id:
                    edges.append(p.default_next_node_id)
            elif isinstance(p, IRLoopPayload):
                if p.body_node_id:
                    edges.append(p.body_node_id)
                if p.next_node_id:
                    edges.append(p.next_node_id)
            elif isinstance(p, IRParallelPayload):
                edges.extend(b.start_node_id for b in p.branches)
                if p.next_node_id:
                    edges.append(p.next_node_id)
            elif isinstance(p, IRHumanApprovalPayload):
                for attr in ("on_approve", "on_reject", "on_timeout"):
                    t = getattr(p, attr, None)
                    if t:
                        edges.append(t)
            elif isinstance(p, IRSubflowPayload):
                if p.next_node_id:
                    edges.append(p.next_node_id)
            for nxt in edges:
                if nxt and nxt not in reachable and nxt in all_node_ids:
                    queue.append(nxt)
        unreachable = all_node_ids - reachable
        for nid in sorted(unreachable):
            errors.append(f"Node '{nid}' is unreachable from start_node '{ir.start_node_id}'.")

    return errors
