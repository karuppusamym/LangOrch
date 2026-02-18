"""Explain / dry-run static analysis service.

No execution, no DB writes, no side effects.
Accepts a compiled IRProcedure and returns a structured report describing:
  - Every node with its type, agent, steps, side-effect flag, SLA, and timeout
  - All edges derived from the IR
  - Variables that the procedure requires (inputs) and produces (outputs)
  - A reachable-node route trace from the start node
  - All external calls (agent_http / mcp_tool steps) flagged with their bindings
  - A policy summary (retry, rate limiting, execution mode)
"""

from __future__ import annotations

from typing import Any

from app.compiler.ir import (
    IRProcedure,
    IRNode,
    IRSequencePayload,
    IRLlmActionPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRParallelPayload,
    IRHumanApprovalPayload,
    IRSubflowPayload,
    IRTransformPayload,
    IRProcessingPayload,
    IRVerificationPayload,
    IRTerminatePayload,
)

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def explain_procedure(
    ir: IRProcedure,
    input_vars: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Return a static analysis report for *ir*.

    Args:
        ir: Compiled IR procedure (output of parser + binder).
        input_vars: Optional dict of provided input variable names → values
            (values not used for computation, only for coverage checks).

    Returns:
        Dict with keys: nodes, edges, variables, route_trace, external_calls,
        policy_summary.
    """
    input_vars = input_vars or {}

    nodes_info = _analyse_nodes(ir)
    edges_info = _analyse_edges(ir)
    variables_info = _analyse_variables(ir, input_vars)
    route_trace = _trace_routes(ir)
    external_calls = _collect_external_calls(ir)
    policy_summary = _summarise_policy(ir)

    return {
        "procedure_id": ir.procedure_id,
        "version": ir.version,
        "nodes": nodes_info,
        "edges": edges_info,
        "variables": variables_info,
        "route_trace": route_trace,
        "external_calls": external_calls,
        "policy_summary": policy_summary,
    }


# ---------------------------------------------------------------------------
# Node analysis
# ---------------------------------------------------------------------------

def _analyse_nodes(ir: IRProcedure) -> list[dict[str, Any]]:
    results = []
    for nid, node in ir.nodes.items():
        entry = {
            "id": nid,
            "type": node.type,
            "agent": node.agent,
            "description": node.description,
            "is_checkpoint": node.is_checkpoint,
            "sla": node.sla,
            "timeout_ms": _node_timeout_ms(node),
            "has_side_effects": _has_side_effects(node),
            "steps": _summarise_steps(node),
            "error_handlers": _summarise_error_handlers(node),
        }
        results.append(entry)
    return results


def _node_timeout_ms(node: IRNode) -> int | None:
    """Return the node-level timeout if any (sequence / llm_action / human_approval)."""
    if isinstance(node.payload, IRHumanApprovalPayload):
        return node.payload.timeout_ms
    if isinstance(node.payload, IRSequencePayload):
        # Return max step timeout as a proxy
        timeouts = [s.timeout_ms for s in node.payload.steps if s.timeout_ms]
        return max(timeouts) if timeouts else None
    return None


def _has_side_effects(node: IRNode) -> bool:
    """True when the node dispatches calls outside the process."""
    if node.type in ("human_approval", "subflow"):
        return True
    if isinstance(node.payload, IRSequencePayload):
        return any(
            s.executor_binding and s.executor_binding.kind in ("agent_http", "mcp_tool")
            for s in node.payload.steps
        )
    if isinstance(node.payload, IRLlmActionPayload):
        return True  # LLM calls are external
    return False


def _summarise_steps(node: IRNode) -> list[dict[str, Any]]:
    if not isinstance(node.payload, IRSequencePayload):
        return []
    return [
        {
            "step_id": s.step_id,
            "action": s.action,
            "timeout_ms": s.timeout_ms,
            "retry_on_failure": s.retry_on_failure,
            "output_variable": s.output_variable,
            "binding_kind": s.executor_binding.kind if s.executor_binding else None,
        }
        for s in node.payload.steps
    ]


def _summarise_error_handlers(node: IRNode) -> list[dict[str, Any]]:
    handlers = getattr(node.payload, "error_handlers", None) or []
    return [
        {
            "error_type": h.error_type,
            "action": h.action,
            "max_retries": h.max_retries,
            "delay_ms": h.delay_ms,
            "fallback_node": h.fallback_node,
        }
        for h in handlers
    ]


# ---------------------------------------------------------------------------
# Edge analysis
# ---------------------------------------------------------------------------

def _analyse_edges(ir: IRProcedure) -> list[dict[str, Any]]:
    edges: list[dict[str, Any]] = []

    for nid, node in ir.nodes.items():
        if node.type == "terminate":
            edges.append({"from": nid, "to": "__end__", "condition": None})
            continue

        if node.type == "logic" and isinstance(node.payload, IRLogicPayload):
            for rule in node.payload.rules:
                edges.append({
                    "from": nid,
                    "to": rule.next_node_id,
                    "condition": rule.condition_expr,
                })
            if node.payload.default_next_node_id:
                edges.append({
                    "from": nid,
                    "to": node.payload.default_next_node_id,
                    "condition": "default",
                })
            continue

        if node.type == "human_approval" and isinstance(node.payload, IRHumanApprovalPayload):
            for attr, label in (
                ("on_approve", "approved"),
                ("on_reject", "rejected"),
                ("on_timeout", "timeout"),
            ):
                target = getattr(node.payload, attr, None)
                if target:
                    edges.append({"from": nid, "to": target, "condition": label})
            continue

        if node.type == "loop" and isinstance(node.payload, IRLoopPayload):
            if node.payload.body_node_id:
                edges.append({"from": nid, "to": node.payload.body_node_id, "condition": "loop_body"})
            if node.payload.next_node_id:
                edges.append({"from": nid, "to": node.payload.next_node_id, "condition": "loop_exit"})
            continue

        if node.type == "parallel" and isinstance(node.payload, IRParallelPayload):
            for branch in node.payload.branches:
                edges.append({"from": nid, "to": branch.start_node_id, "condition": f"branch:{branch.branch_id}"})
            if node.payload.next_node_id:
                edges.append({"from": nid, "to": node.payload.next_node_id, "condition": "parallel_join"})
            continue

        # Simple sequential edges
        next_id = node.next_node_id or (
            getattr(node.payload, "next_node_id", None) if node.payload else None
        )
        if next_id:
            edges.append({"from": nid, "to": next_id, "condition": None})
        else:
            edges.append({"from": nid, "to": "__end__", "condition": None})

    return edges


# ---------------------------------------------------------------------------
# Variable analysis
# ---------------------------------------------------------------------------

def _analyse_variables(
    ir: IRProcedure, provided: dict[str, Any]
) -> dict[str, Any]:
    schema = ir.variables_schema or {}
    required: list[str] = []
    produced: list[str] = []
    missing: list[str] = []

    for var_name, var_def in schema.items():
        if isinstance(var_def, dict):
            if var_def.get("required", False):
                required.append(var_name)
                if var_name not in provided:
                    missing.append(var_name)
        else:
            required.append(var_name)

    # Collect output_variables from steps
    for node in ir.nodes.values():
        if isinstance(node.payload, IRSequencePayload):
            for step in node.payload.steps:
                if step.output_variable and step.output_variable not in produced:
                    produced.append(step.output_variable)
        if isinstance(node.payload, IRLlmActionPayload):
            for out_var in (node.payload.outputs or {}).values():
                if out_var not in produced:
                    produced.append(out_var)
        if isinstance(node.payload, IRTransformPayload):
            for op in node.payload.transformations:
                if op.output_variable not in produced:
                    produced.append(op.output_variable)

    return {
        "schema": schema,
        "required": required,
        "produced": produced,
        "missing_inputs": missing,
        "provided": list(provided.keys()),
    }


# ---------------------------------------------------------------------------
# Route trace (reachability from start node)
# ---------------------------------------------------------------------------

def _trace_routes(ir: IRProcedure) -> list[dict[str, Any]]:
    """BFS from start_node_id to collect reachable nodes and their next links."""
    visited: set[str] = set()
    queue: list[str] = [ir.start_node_id] if ir.start_node_id else []
    trace: list[dict[str, Any]] = []

    while queue:
        nid = queue.pop(0)
        if nid in visited or nid not in ir.nodes:
            continue
        visited.add(nid)
        node = ir.nodes[nid]
        next_nodes = _get_next_nodes(node)
        trace.append({
            "node_id": nid,
            "type": node.type,
            "next_nodes": next_nodes,
            "is_terminal": node.type == "terminate" or not next_nodes,
        })
        for n in next_nodes:
            if n and n not in visited and n in ir.nodes:
                queue.append(n)

    return trace


def _get_next_nodes(node: IRNode) -> list[str]:
    results: list[str] = []

    if node.type == "logic" and isinstance(node.payload, IRLogicPayload):
        results.extend(r.next_node_id for r in node.payload.rules if r.next_node_id)
        if node.payload.default_next_node_id:
            results.append(node.payload.default_next_node_id)
    elif node.type == "human_approval" and isinstance(node.payload, IRHumanApprovalPayload):
        for attr in ("on_approve", "on_reject", "on_timeout"):
            t = getattr(node.payload, attr, None)
            if t:
                results.append(t)
    elif node.type == "loop" and isinstance(node.payload, IRLoopPayload):
        if node.payload.body_node_id:
            results.append(node.payload.body_node_id)
        if node.payload.next_node_id:
            results.append(node.payload.next_node_id)
    elif node.type == "parallel" and isinstance(node.payload, IRParallelPayload):
        results.extend(b.start_node_id for b in node.payload.branches if b.start_node_id)
        if node.payload.next_node_id:
            results.append(node.payload.next_node_id)
    else:
        nxt = node.next_node_id or (
            getattr(node.payload, "next_node_id", None) if node.payload else None
        )
        if nxt:
            results.append(nxt)

    return [n for n in results if n]


# ---------------------------------------------------------------------------
# External calls
# ---------------------------------------------------------------------------

def _collect_external_calls(ir: IRProcedure) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    for nid, node in ir.nodes.items():
        if isinstance(node.payload, IRSequencePayload):
            for step in node.payload.steps:
                if step.executor_binding and step.executor_binding.kind in ("agent_http", "mcp_tool"):
                    calls.append({
                        "node_id": nid,
                        "step_id": step.step_id,
                        "action": step.action,
                        "binding_kind": step.executor_binding.kind,
                        "binding_ref": step.executor_binding.ref,
                        "agent_hint": node.agent,
                        "timeout_ms": step.timeout_ms,
                    })
        elif node.type == "llm_action" and isinstance(node.payload, IRLlmActionPayload):
            calls.append({
                "node_id": nid,
                "step_id": None,
                "action": "llm_inference",
                "binding_kind": "llm",
                "binding_ref": node.payload.model,
                "agent_hint": node.agent,
                "timeout_ms": None,
            })
        elif node.type == "subflow" and isinstance(node.payload, IRSubflowPayload):
            calls.append({
                "node_id": nid,
                "step_id": None,
                "action": "subflow",
                "binding_kind": "subflow",
                "binding_ref": f"{node.payload.procedure_id}@{node.payload.version or 'latest'}",
                "agent_hint": None,
                "timeout_ms": None,
            })
        elif node.type == "human_approval":
            calls.append({
                "node_id": nid,
                "step_id": None,
                "action": "human_approval",
                "binding_kind": "human",
                "binding_ref": None,
                "agent_hint": None,
                "timeout_ms": node.payload.timeout_ms if isinstance(node.payload, IRHumanApprovalPayload) else None,
            })

    return calls


# ---------------------------------------------------------------------------
# Policy summary
# ---------------------------------------------------------------------------

def _summarise_policy(ir: IRProcedure) -> dict[str, Any]:
    gc = ir.global_config or {}
    return {
        "execution_mode": gc.get("execution_mode", "sequential"),
        "timeout_ms": gc.get("timeout_ms"),
        "retry": gc.get("retry_policy") or {
            "max_retries": gc.get("max_retries", 3),
            "retry_delay_ms": gc.get("retry_delay_ms", 1000),
            "backoff_multiplier": gc.get("backoff_multiplier", 2.0),
        },
        "rate_limiting": gc.get("rate_limiting", {}),
        "checkpoint_strategy": gc.get("checkpoint_strategy"),
        "retention_days": gc.get("retention_days"),
    }
