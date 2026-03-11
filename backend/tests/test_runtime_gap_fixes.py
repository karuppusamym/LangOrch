from __future__ import annotations

import asyncio
import time

import pytest

from app.compiler.ir import (
    IRHumanApprovalPayload,
    IRLlmActionPayload,
    IRLoopPayload,
    IRNode,
    IRParallelBranch,
    IRParallelPayload,
    IRProcessingOp,
    IRSequencePayload,
    IRSubflowPayload,
    IRTerminatePayload,
)
from app.runtime import node_executors


@pytest.mark.asyncio
async def test_execute_parallel_runs_branches_concurrently(monkeypatch):
    node = IRNode(
        node_id="parallel_node",
        type="parallel",
        payload=IRParallelPayload(
            branches=[
                IRParallelBranch(branch_id="a", start_node_id="branch_a"),
                IRParallelBranch(branch_id="b", start_node_id="branch_b"),
            ],
            next_node_id="done",
            wait_strategy="all",
        ),
    )

    async def fake_execute_branch_path(start_node_id, join_node_id, state, nodes, db_factory=None):
        await asyncio.sleep(0.1)
        return {**state, "vars": {**state.get("vars", {}), start_node_id: True}}

    monkeypatch.setattr(node_executors, "_execute_branch_path", fake_execute_branch_path)

    started = time.monotonic()
    result = await node_executors.execute_parallel(
        node,
        {"vars": {}},
        nodes={
            "branch_a": IRNode(node_id="branch_a", type="sequence", payload=IRSequencePayload()),
            "branch_b": IRNode(node_id="branch_b", type="sequence", payload=IRSequencePayload()),
        },
    )
    elapsed = time.monotonic() - started

    assert elapsed < 0.18
    assert result["vars"]["parallel_results"]["branches"]["a"] == {"branch_a": True}
    assert result["vars"]["parallel_results"]["branches"]["b"] == {"branch_b": True}


@pytest.mark.asyncio
async def test_execute_node_awaits_llm_action(monkeypatch):
    async def fake_execute_llm_action(node, state, db_factory=None):
        return {**state, "vars": {"llm": "ok"}, "next_node_id": "done", "current_node_id": node.node_id}

    monkeypatch.setattr(node_executors, "execute_llm_action", fake_execute_llm_action)

    result = await node_executors._execute_node(
        IRNode(node_id="llm", type="llm_action", payload=IRLlmActionPayload(prompt="hi")),
        {"vars": {}},
        nodes={},
        db_factory=object(),
    )

    assert result["vars"]["llm"] == "ok"
    assert result["next_node_id"] == "done"


@pytest.mark.asyncio
async def test_execute_node_supports_subflow(monkeypatch):
    async def fake_execute_subflow(node, state, db_factory=None):
        return {**state, "vars": {"subflow": "ok"}, "next_node_id": "done", "current_node_id": node.node_id}

    monkeypatch.setattr(node_executors, "execute_subflow", fake_execute_subflow)

    result = await node_executors._execute_node(
        IRNode(node_id="sub", type="subflow", payload=IRSubflowPayload(procedure_id="child")),
        {"vars": {}},
        nodes={},
        db_factory=object(),
    )

    assert result["vars"]["subflow"] == "ok"
    assert result["next_node_id"] == "done"


@pytest.mark.asyncio
async def test_execute_loop_runtime_honors_max_iterations_and_collect_variable(monkeypatch):
    async def fake_execute_branch_path(start_node_id, join_node_id, state, nodes, db_factory=None):
        return state

    monkeypatch.setattr(node_executors, "_execute_branch_path", fake_execute_branch_path)

    node = IRNode(
        node_id="loop_node",
        type="loop",
        payload=IRLoopPayload(
            iterator_var="items",
            iterator_variable="current_item",
            index_variable="idx",
            body_node_id="body",
            collect_variable="processed_items",
            max_iterations=2,
            next_node_id="done",
        ),
    )

    result = await node_executors.execute_loop_runtime(
        node,
        {
            "vars": {"items": ["a", "b", "c"]},
            "loop_index": 0,
            "run_id": "run1",
            "procedure_id": "proc1",
            "events": [],
        },
        nodes={"body": IRNode(node_id="body", type="sequence", payload=IRSequencePayload())},
    )

    assert result["next_node_id"] == "done"
    assert result["vars"]["processed_items"] == ["a", "b"]
    assert result["loop_results"] == ["a", "b"]
    loop_events = [event for event in result["events"] if event["event_type"] == "loop_iteration"]
    assert len(loop_events) == 2


@pytest.mark.asyncio
async def test_execute_loop_runtime_continue_on_error(monkeypatch):
    async def fake_execute_branch_path(start_node_id, join_node_id, state, nodes, db_factory=None):
        if state.get("loop_index") == 0:
            return {
                **state,
                "error": {"message": "boom"},
                "terminal_status": "failed",
            }
        return state

    monkeypatch.setattr(node_executors, "_execute_branch_path", fake_execute_branch_path)

    node = IRNode(
        node_id="loop_node",
        type="loop",
        payload=IRLoopPayload(
            iterator_var="items",
            iterator_variable="current_item",
            body_node_id="body",
            continue_on_error=True,
            collect_variable="processed_items",
            next_node_id="done",
        ),
    )

    result = await node_executors.execute_loop_runtime(
        node,
        {
            "vars": {"items": ["bad", "good"]},
            "loop_index": 0,
            "run_id": "run1",
            "procedure_id": "proc1",
            "events": [],
        },
        nodes={"body": IRNode(node_id="body", type="sequence", payload=IRSequencePayload())},
    )

    assert result.get("error") is None
    assert result["next_node_id"] == "done"
    assert result["vars"]["processed_items"] == ["good"]


def test_execute_human_approval_includes_timeout_metadata():
    result = node_executors.execute_human_approval(
        IRNode(
            node_id="approval",
            type="human_approval",
            description="Manager approval",
            payload=IRHumanApprovalPayload(
                prompt="Approve?",
                timeout_ms=5000,
                timeout_action="reject",
                approval_level="L2",
                escalation_contact="ops@example.com",
            ),
        ),
        {"vars": {}, "run_id": "run1", "procedure_id": "proc1"},
    )

    assert result["awaiting_approval"]["timeout_ms"] == 5000
    assert result["awaiting_approval"]["timeout_action"] == "reject"
    assert result["awaiting_approval"]["approval_level"] == "L2"
    assert result["awaiting_approval"]["escalation_contact"] == "ops@example.com"


def test_execute_terminate_applies_outputs_and_cleanup_actions():
    result = node_executors.execute_terminate(
        IRNode(
            node_id="end",
            type="terminate",
            payload=IRTerminatePayload(
                status="success",
                cleanup_actions=[
                    IRProcessingOp(action="set_variable", params={"variable": "cleanup_done", "value": True})
                ],
                outputs={
                    "result": "source_value",
                    "literal": "done",
                },
            ),
        ),
        {
            "vars": {"source_value": "resolved"},
            "run_id": "run1",
            "procedure_id": "proc1",
        },
    )

    assert result["vars"]["cleanup_done"] is True
    assert result["vars"]["result"] == "resolved"
    assert result["vars"]["literal"] == "done"


@pytest.mark.asyncio
async def test_execute_subflow_blocks_recursive_call_stack():
    result = await node_executors.execute_subflow(
        IRNode(
            node_id="sub",
            type="subflow",
            payload=IRSubflowPayload(procedure_id="parent_proc"),
        ),
        {
            "vars": {},
            "run_id": "run1",
            "procedure_id": "child_proc",
            "_subflow_stack": ["parent_proc", "root_proc"],
        },
        db_factory=None,
    )

    assert result["terminal_status"] == "failed"
    assert "Recursive subflow detected" in result["error"]["message"]