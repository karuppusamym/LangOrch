"""Graph builder — compiles IR into a LangGraph StateGraph."""

from __future__ import annotations

import logging
from typing import Any, Callable

from langgraph.graph import StateGraph, END

from app.compiler.ir import (
    IRHumanApprovalPayload,
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
_NEEDS_DB: set[str] = {"sequence", "subflow"}


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

    # Add a node function for every CKP node
    for nid, ir_node in ir.nodes.items():
        executor = _NODE_EXECUTORS.get(ir_node.type)
        if not executor:
            logger.warning("No executor for node type '%s', skipping node '%s'", ir_node.type, nid)
            continue

        # Closure to capture ir_node and db_factory
        def make_fn(node: IRNode, needs_db: bool):
            if node.type == "parallel":
                async def fn(state: OrchestratorState) -> OrchestratorState:
                    return await execute_parallel(node, state, db_factory=db_factory, nodes=ir.nodes)
            elif needs_db:
                async def fn(state: OrchestratorState) -> OrchestratorState:
                    return await _NODE_EXECUTORS[node.type](node, state, db_factory=db_factory)
            else:
                def fn(state: OrchestratorState) -> OrchestratorState:
                    return _NODE_EXECUTORS[node.type](node, state)
            fn.__name__ = f"node_{node.node_id}"
            return fn

        graph.add_node(nid, make_fn(ir_node, ir_node.type in _NEEDS_DB))

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

    else:
        # Generic: next_node_id or payload.next_node_id
        for target in [ir_node.next_node_id, getattr(ir_node.payload, "next_node_id", None)]:
            if target:
                destinations[target] = target

    graph.add_conditional_edges(nid, router, destinations)
