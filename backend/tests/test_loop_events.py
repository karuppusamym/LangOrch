"""Tests for loop_iteration event emission.

Covers:
  1. execute_loop emits loop_iteration events with index/total/item
  2. loop_iteration events are not emitted when loop is complete
"""

from __future__ import annotations

import pytest
from app.runtime.node_executors import execute_loop


class _FakePayload:
    """Minimal IRLoopPayload stand-in."""
    def __init__(self):
        self.iterator_var = "items"
        self.iterator_variable = "current_item"
        self.index_variable = "idx"
        self.body_node_id = "loop_body"
        self.next_node_id = "done"


class _FakeNode:
    """Minimal IRNode stand-in."""
    def __init__(self):
        self.node_id = "loop_node"
        self.payload = _FakePayload()


# ── 1. Loop iteration event is emitted ──────────────────────────────────────


def test_loop_iteration_emits_event():
    """Each loop iteration should produce a loop_iteration event."""
    node = _FakeNode()
    state = {
        "vars": {"items": ["a", "b", "c"]},
        "loop_index": 0,
        "run_id": "test_run",
        "procedure_id": "test_proc",
        "events": [],
    }

    result = execute_loop(node, state)

    # Should have one loop_iteration event
    events = result.get("events", [])
    assert len(events) == 1
    ev = events[0]
    assert ev["event_type"] == "loop_iteration"
    assert ev["node_id"] == "loop_node"
    assert ev["payload"]["iteration"] == 0
    assert ev["payload"]["total"] == 3
    assert ev["payload"]["item"] == "a"

    # Loop vars should be set
    assert result["vars"]["current_item"] == "a"
    assert result["vars"]["idx"] == 0
    assert result["next_node_id"] == "loop_body"


# ── 2. Loop complete does not emit iteration event ──────────────────────────


def test_loop_complete_no_event():
    """When the loop is complete, no loop_iteration event should be emitted."""
    node = _FakeNode()
    state = {
        "vars": {"items": ["a", "b"]},
        "loop_index": 2,  # past end of iterator
        "run_id": "test_run",
        "procedure_id": "test_proc",
        "events": [],
    }

    result = execute_loop(node, state)

    # No loop_iteration events
    events = result.get("events", [])
    assert len(events) == 0  # events list is unchanged (empty)

    # Should reset loop_index and route to next_node
    assert result["loop_index"] == 0
    assert result["next_node_id"] == "done"
