"""Graph builder — compiles IR into a LangGraph StateGraph."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable

from langgraph.graph import StateGraph, END

from app.utils.token_bucket import acquire_rate_limit
from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLlmActionPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRNode,
    IRProcedure,
    IRTerminatePayload,
)
from app.runtime.node_executors import (
    execute_human_approval,
    execute_llm_action,
    execute_logic,
    execute_loop,
    execute_parallel,
    execute_processing,
    execute_sequence,
    execute_subflow,
    execute_terminate,
    execute_transform,
    execute_verification,
)
from app.runtime.state import OrchestratorState

logger = logging.getLogger("langorch.graph_builder")


async def _emit_node_lifecycle(
    db_factory: Callable | None,
    run_id: str,
    event_type: str,
    node_id: str,
    payload: dict[str, Any] | None = None,
) -> None:
    """Emit a node-level lifecycle event (node_started / node_completed / node_error)."""
    if not db_factory or not run_id:
        return
    try:
        from app.services import run_service
        async with db_factory() as db:
            await run_service.emit_event(
                db, run_id, event_type,
                node_id=node_id,
                payload=payload,
            )
            await db.commit()
    except Exception as exc:
        logger.warning("Failed to emit %s for node %s: %s", event_type, node_id, exc)


async def _check_sla(
    node_id: str,
    t0: float,
    max_ms: int,
    on_breach: str,
    escalation_handler: str | None,
    state: OrchestratorState,
    db_factory: Callable | None,
) -> dict | None:
    """Check SLA timing after a node completes.

    Returns a state-patch dict if routing should be overridden (escalate mode),
    raises RuntimeError if on_breach=="fail", returns None otherwise.
    """
    elapsed_ms = (asyncio.get_event_loop().time() - t0) * 1000.0
    if elapsed_ms <= max_ms:
        return None
    run_id = state.get("run_id", "")
    logger.warning(
        "SLA breach: node '%s' took %.0fms, limit %dms (on_breach=%s)",
        node_id, elapsed_ms, max_ms, on_breach,
    )
    if db_factory and run_id:
        from app.services import run_service
        try:
            async with db_factory() as db:
                await run_service.emit_event(
                    db, run_id, "sla_breached",
                    node_id=node_id,
                    payload={
                        "elapsed_ms": round(elapsed_ms),
                        "limit_ms": max_ms,
                        "on_breach": on_breach,
                        "escalation_handler": escalation_handler,
                    },
                )
                await db.commit()
        except Exception as exc:
            logger.warning("Failed to emit sla_breached event: %s", exc)

    if on_breach == "fail":
        raise RuntimeError(
            f"SLA breach: node '{node_id}' exceeded {max_ms}ms limit "
            f"(took {round(elapsed_ms)}ms)"
        )
    if on_breach == "escalate" and escalation_handler:
        logger.info(
            "SLA breach escalation: routing node '%s' → '%s'",
            node_id, escalation_handler,
        )
        return {"next_node_id": escalation_handler}
    return None

# Map CKP node type → executor function
_NODE_EXECUTORS: dict[str, Any] = {
    "sequence": execute_sequence,
    "logic": execute_logic,
    "loop": execute_loop,
    "parallel": execute_parallel,
    "processing": execute_processing,
    "verification": execute_verification,
    "llm_action": execute_llm_action,
    "human_approval": execute_human_approval,
    "transform": execute_transform,
    "subflow": execute_subflow,
    "terminate": execute_terminate,
}

# Node types whose executors need db_factory (for dynamic agent dispatch)
_NEEDS_DB: set[str] = {"sequence", "subflow", "llm_action"}


def build_graph(
    ir: IRProcedure,
    db_factory: Callable | None = None,
    entry_node_id: str | None = None,
) -> StateGraph:
    """Convert an IRProcedure into a LangGraph StateGraph ready for compilation.

    Args:
        ir: Compiled IR procedure.
        db_factory: Async context-manager factory for DB sessions.
            Needed at runtime for dynamic agent dispatch in sequence nodes.
        entry_node_id: Optional override for graph entry point.
            Used for resume flows (e.g., continue from paused approval node).
    """

    graph = StateGraph(OrchestratorState)

    # Build optional concurrency semaphore from global_config rate_limiting
    _rate_cfg = ir.global_config.get("rate_limiting") or {}
    _max_concurrent: int | None = (
        int(_rate_cfg["max_concurrent_operations"])
        if _rate_cfg.get("enabled") and _rate_cfg.get("max_concurrent_operations")
        else None
    )
    _semaphore: asyncio.Semaphore | None = (
        asyncio.Semaphore(_max_concurrent) if _max_concurrent and _max_concurrent > 0 else None
    )
    if _semaphore:
        logger.info(
            "Rate limiting: max_concurrent_operations=%d for procedure '%s'",
            _max_concurrent, ir.procedure_id,
        )

    _max_rpm: int | None = (
        int(_rate_cfg["max_requests_per_minute"])
        if _rate_cfg.get("enabled") and _rate_cfg.get("max_requests_per_minute")
        else None
    )
    if _max_rpm:
        logger.info(
            "Rate limiting: max_requests_per_minute=%d for procedure '%s'",
            _max_rpm, ir.procedure_id,
        )

    # Add a node function for every CKP node
    for nid, ir_node in ir.nodes.items():
        executor = _NODE_EXECUTORS.get(ir_node.type)
        if not executor:
            logger.warning("No executor for node type '%s', skipping node '%s'", ir_node.type, nid)
            continue

        # Closure to capture ir_node, db_factory, and semaphore
        def make_fn(node: IRNode, needs_db: bool, sem: asyncio.Semaphore | None, max_rpm: int | None = None):
            _sla = node.sla or {}
            _max_ms: int | None = int(_sla["max_duration_ms"]) if _sla.get("max_duration_ms") else None
            _on_breach: str = str(_sla.get("on_breach") or "warn")
            _escalation_handler: str | None = _sla.get("escalation_handler") or None
            _custom_metrics: list | None = (node.telemetry or {}).get("custom_metrics")
            _is_ckp: bool = node.is_checkpoint  # capture for closure

            def _emit_custom_metrics():
                if _custom_metrics:
                    from app.utils.metrics import record_custom_metric
                    for cm in _custom_metrics:
                        if isinstance(cm, str):
                            record_custom_metric(cm)
                        elif isinstance(cm, dict) and cm.get("name"):
                            record_custom_metric(cm["name"], value=int(cm.get("value", 1)))

            def _apply_checkpoint_marker(result: OrchestratorState, node_id: str) -> OrchestratorState:
                """Inject _checkpoint_node_id so execution_service can force-save."""
                if _is_ckp:
                    return {**result, "_checkpoint_node_id": node_id}
                return result

            if node.type == "parallel":
                async def fn(state: OrchestratorState) -> OrchestratorState:
                    async def _run():
                        if max_rpm:
                            await acquire_rate_limit(ir.procedure_id, max_rpm)
                        _t0 = asyncio.get_event_loop().time()
                        result = await execute_parallel(node, state, db_factory=db_factory, nodes=ir.nodes)
                        _emit_custom_metrics()
                        if _max_ms:
                            patch = await _check_sla(node.node_id, _t0, _max_ms, _on_breach, _escalation_handler, state, db_factory)
                            if patch:
                                result = {**result, **patch}
                        return _apply_checkpoint_marker(result, node.node_id)
                    if sem:
                        async with sem:
                            return await _run()
                    return await _run()
            elif needs_db:
                async def fn(state: OrchestratorState) -> OrchestratorState:
                    async def _run():
                        if max_rpm:
                            await acquire_rate_limit(ir.procedure_id, max_rpm)
                        _t0 = asyncio.get_event_loop().time()
                        result = await _NODE_EXECUTORS[node.type](node, state, db_factory=db_factory)
                        _emit_custom_metrics()
                        if _max_ms:
                            patch = await _check_sla(node.node_id, _t0, _max_ms, _on_breach, _escalation_handler, state, db_factory)
                            if patch:
                                result = {**result, **patch}
                        return _apply_checkpoint_marker(result, node.node_id)
                    if sem:
                        async with sem:
                            return await _run()
                    return await _run()
            else:
                def fn(state: OrchestratorState) -> OrchestratorState:
                    result = _NODE_EXECUTORS[node.type](node, state)
                    return _apply_checkpoint_marker(result, node.node_id)

            # Wrap fn with node-level lifecycle event emission
            _base_fn = fn
            _is_async = asyncio.iscoroutinefunction(_base_fn)
            _nid = node.node_id  # capture for closure
            _node_name = node.description or node.node_id  # human-readable name for events

            async def fn(
                state: OrchestratorState,
                _bfn: Any = _base_fn,
                _ia: bool = _is_async,
                _node_id: str = _nid,
                _nname: str = _node_name,
            ) -> OrchestratorState:
                _rid = state.get("run_id", "")
                await _emit_node_lifecycle(db_factory, _rid, "node_started", _node_id,
                                           payload={"node_name": _nname})
                try:
                    result = (await _bfn(state)) if _ia else _bfn(state)
                    # Emit node_paused instead of node_completed when the node is
                    # waiting for an external signal (human approval, async workflow).
                    _ts = result.get("terminal_status") if isinstance(result, dict) else None
                    if _ts == "awaiting_approval" or result.get("_workflow_pending"):
                        await _emit_node_lifecycle(db_factory, _rid, "node_paused", _node_id,
                                                   payload={"reason": _ts or "workflow_pending",
                                                            "node_name": _nname})
                    else:
                        await _emit_node_lifecycle(db_factory, _rid, "node_completed", _node_id,
                                                   payload={"node_name": _nname})
                    return result
                except Exception as exc:
                    await _emit_node_lifecycle(
                        db_factory, _rid, "node_error", _node_id,
                        payload={"error": str(exc)[:500], "node_name": _nname},
                    )
                    raise

            fn.__name__ = f"node_{node.node_id}"
            return fn

        graph.add_node(nid, make_fn(ir_node, ir_node.type in _NEEDS_DB, _semaphore, _max_rpm))

    # Set entry point (default = procedure start)
    graph.set_entry_point(entry_node_id or ir.start_node_id)

    # Add edges based on node types
    for nid, ir_node in ir.nodes.items():
        if ir_node.type not in _NODE_EXECUTORS:
            continue

        if ir_node.type == "terminate":
            graph.add_edge(nid, END)

        elif ir_node.type == "logic":
            # Conditional edges based on next_node_id in state
            _add_conditional_routing(graph, nid, ir_node, ir)

        elif ir_node.type == "human_approval":
            _add_conditional_routing(graph, nid, ir_node, ir)

        elif ir_node.type == "loop":
            _add_conditional_routing(graph, nid, ir_node, ir)

        elif ir_node.type == "llm_action" and isinstance(ir_node.payload, IRLlmActionPayload) and ir_node.payload.orchestration_mode:
            # Orchestration-mode llm_action: runtime picks next node from LLM output
            _add_conditional_routing(graph, nid, ir_node, ir)

        else:
            # Simple edge to next_node or END
            if ir_node.next_node_id and ir_node.next_node_id in ir.nodes:
                graph.add_edge(nid, ir_node.next_node_id)
            elif ir_node.payload and hasattr(ir_node.payload, "next_node_id") and ir_node.payload.next_node_id:
                graph.add_edge(nid, ir_node.payload.next_node_id)
            else:
                graph.add_edge(nid, END)

    return graph


def _add_conditional_routing(
    graph: StateGraph, nid: str, ir_node: IRNode, ir: IRProcedure
) -> None:
    """Add conditional edge that reads next_node_id from state output."""
    valid_targets = set(ir.nodes.keys())

    def router(state: OrchestratorState) -> str:
        target = state.get("next_node_id")
        if target and target in valid_targets:
            return target
        return END

    # Collect all possible destinations for this node
    destinations: dict[str, str] = {END: END}
    if ir_node.type == "logic" and isinstance(ir_node.payload, IRLogicPayload):
        for rule in ir_node.payload.rules:
            destinations[rule.next_node_id] = rule.next_node_id
        if ir_node.payload.default_next_node_id:
            destinations[ir_node.payload.default_next_node_id] = ir_node.payload.default_next_node_id

    elif ir_node.type == "human_approval" and isinstance(ir_node.payload, IRHumanApprovalPayload):
        for attr in ("on_approve", "on_reject", "on_timeout"):
            t = getattr(ir_node.payload, attr, None)
            if t:
                destinations[t] = t

    elif ir_node.type == "loop" and isinstance(ir_node.payload, IRLoopPayload):
        if ir_node.payload.body_node_id:
            destinations[ir_node.payload.body_node_id] = ir_node.payload.body_node_id
        if ir_node.payload.next_node_id:
            destinations[ir_node.payload.next_node_id] = ir_node.payload.next_node_id

    elif ir_node.type == "llm_action" and isinstance(ir_node.payload, IRLlmActionPayload):
        # Orchestration-mode: all declared branches are valid destinations
        for branch in ir_node.payload.branches:
            if branch:
                destinations[branch] = branch

    else:
        # Generic: next_node_id or payload.next_node_id
        for target in [ir_node.next_node_id, getattr(ir_node.payload, "next_node_id", None)]:
            if target:
                destinations[target] = target

    graph.add_conditional_edges(nid, router, destinations)
