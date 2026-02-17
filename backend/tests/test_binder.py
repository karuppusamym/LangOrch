"""Tests for CKP binder — bind_executors function."""

from __future__ import annotations

import pytest

from app.compiler.parser import parse_ckp
from app.compiler.binder import bind_executors


class TestBindExecutors:
    def test_internal_actions_bound(self, minimal_ckp):
        """Internal actions (log, set_variable, etc.) should be bound."""
        ir = parse_ckp(minimal_ckp)
        ir = bind_executors(ir)
        step = ir.nodes["start"].payload.steps[0]
        assert step.executor_binding is not None
        assert step.executor_binding.kind == "internal"
        assert step.executor_binding.ref == "log"

    def test_set_variable_bound(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        ir = bind_executors(ir)
        step = ir.nodes["init"].payload.steps[1]
        assert step.executor_binding is not None
        assert step.executor_binding.kind == "internal"
        assert step.executor_binding.ref == "set_variable"

    def test_unknown_actions_unbound(self):
        """Non-internal actions should remain unbound (resolved at runtime)."""
        ckp = {
            "procedure_id": "p",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "s",
                "nodes": {
                    "s": {
                        "type": "sequence",
                        "steps": [
                            {"step_id": "ext", "action": "call_external_api"},
                        ],
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        ir = bind_executors(ir)
        step = ir.nodes["s"].payload.steps[0]
        assert step.executor_binding is None

    def test_non_sequence_nodes_unaffected(self, ckp_with_parallel):
        """Binder should only process sequence nodes, not crash on others."""
        ir = parse_ckp(ckp_with_parallel)
        ir = bind_executors(ir)  # should not raise
        # Parallel node payload should be unaffected
        assert ir.nodes["par"].payload is not None

    def test_multiple_internal_actions(self):
        """All recognized internal actions should be bound."""
        internal_actions = [
            "log", "wait", "set_variable", "calculate", "format_data",
            "parse_json", "parse_csv", "generate_id", "get_timestamp",
            "set_checkpoint", "restore_checkpoint", "screenshot",
        ]
        ckp = {
            "procedure_id": "p",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "s",
                "nodes": {
                    "s": {
                        "type": "sequence",
                        "steps": [
                            {"step_id": f"step_{a}", "action": a}
                            for a in internal_actions
                        ],
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        ir = bind_executors(ir)
        for step in ir.nodes["s"].payload.steps:
            assert step.executor_binding is not None, f"{step.action} should be bound"
            assert step.executor_binding.kind == "internal"
            assert step.executor_binding.ref == step.action

    def test_returns_same_ir(self, minimal_ckp):
        """bind_executors should return the same IRProcedure object."""
        ir = parse_ckp(minimal_ckp)
        result = bind_executors(ir)
        assert result is ir
