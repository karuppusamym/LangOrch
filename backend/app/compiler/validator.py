"""CKP static validator — checks IR integrity before execution."""

from __future__ import annotations

import json
import re
from collections import deque

from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLlmActionPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRParallelPayload,
    IRProcedure,
    IRSequencePayload,
    IRSubflowPayload,
)

_VALID_TRIGGER_TYPES = frozenset({"manual", "scheduled", "webhook", "event", "file_watch"})

# Regex to extract Jinja2 template variable names from CKP text fields
_JINJA_VAR_RE = re.compile(r"\{\{\s*([a-zA-Z_][a-zA-Z0-9_]*)\s*\}\}")

# Actions handled internally by the orchestrator (no agent required)
_STATIC_INTERNAL_ACTIONS: frozenset[str] = frozenset({
    "log", "wait", "set_variable", "calculate", "format_data",
    "parse_json", "parse_csv", "generate_id", "get_timestamp",
    "set_checkpoint", "restore_checkpoint", "screenshot",
})

# Variables always available at runtime even without explicit schema declaration
_IMPLICIT_RUNTIME_VARS: frozenset[str] = frozenset({
    "run_id", "procedure_id", "trigger_type", "triggered_by",
    "node_id", "step_id", "loop_index", "loop_item", "parallel_results",
    "llm_output",
})


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
            # Detect direct self-recursion (this procedure calling itself)
            if payload.procedure_id and payload.procedure_id == ir.procedure_id:
                errors.append(
                    f"Node '{nid}': subflow references its own procedure '{ir.procedure_id}' "
                    f"(direct self-recursion — creates an infinite loop)."
                )

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

    # ── Template variable enforcement ──────────────────────────────
    # Collect all variable names that are "known" by the time any step runs.
    _all_known_vars: set[str] = set(ir.variables_schema or {})
    _all_known_vars |= _IMPLICIT_RUNTIME_VARS
    for _n in ir.nodes.values():
        _p = _n.payload
        if isinstance(_p, IRSequencePayload):
            for _s in _p.steps:
                if _s.output_variable:
                    _all_known_vars.add(_s.output_variable)
        elif isinstance(_p, IRLlmActionPayload):
            _all_known_vars.update(_p.outputs.keys())
        elif isinstance(_p, IRLoopPayload):
            for _v in (_p.iterator_variable, _p.index_variable, _p.collect_variable):
                if _v:
                    _all_known_vars.add(_v)
    # Only enforce when the procedure declares a non-empty variables_schema
    if ir.variables_schema:
        for nid, node in ir.nodes.items():
            payload = node.payload
            if isinstance(payload, IRSequencePayload):
                for step in payload.steps:
                    _params_text = json.dumps(step.params) if step.params else ""
                    _idem_text = step.idempotency_key or ""
                    for _var in _JINJA_VAR_RE.findall(_params_text + " " + _idem_text):
                        if _var not in _all_known_vars:
                            errors.append(
                                f"Node '{nid}', step '{step.step_id}': template references "
                                f"undeclared variable '{{{{{_var}}}}}'."
                            )
            elif isinstance(payload, IRLlmActionPayload):
                _llm_text = (payload.prompt or "") + " " + (payload.system_prompt or "")
                for _var in _JINJA_VAR_RE.findall(_llm_text):
                    if _var not in _all_known_vars:
                        errors.append(
                            f"Node '{nid}' (llm_action): prompt references undeclared variable "
                            f"'{{{{{_var}}}}}'."
                        )

    # ── Action / channel compatibility ─────────────────────────────
    # Sequence steps with non-internal actions must be attached to a node that
    # declares an 'agent' (channel), otherwise the step will be unresolvable at runtime.
    for nid, node in ir.nodes.items():
        payload = node.payload
        if isinstance(payload, IRSequencePayload) and not node.agent:
            for step in payload.steps:
                if step.action not in _STATIC_INTERNAL_ACTIONS:
                    errors.append(
                        f"Node '{nid}', step '{step.step_id}': action '{step.action}' is not a "
                        f"built-in internal action, but node '{nid}' has no 'agent' field set. "
                        f"The step may be unresolvable at runtime."
                    )

    return errors
