"""Tests for CKP validator — validate_ir function."""

from __future__ import annotations

import pytest

from app.compiler.parser import parse_ckp
from app.compiler.validator import validate_ir


class TestValidateValid:
    """Valid CKPs should produce zero errors."""

    def test_minimal_valid(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        errors = validate_ir(ir)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_complex_valid(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        errors = validate_ir(ir)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_parallel_valid(self, ckp_with_parallel):
        ir = parse_ckp(ckp_with_parallel)
        errors = validate_ir(ir)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_human_approval_valid(self, ckp_with_human_approval):
        ir = parse_ckp(ckp_with_human_approval)
        errors = validate_ir(ir)
        assert errors == [], f"Unexpected errors: {errors}"

    def test_subflow_valid(self, ckp_with_subflow):
        ir = parse_ckp(ckp_with_subflow)
        errors = validate_ir(ir)
        assert errors == [], f"Unexpected errors: {errors}"


class TestValidateInvalid:
    """Invalid CKPs should report specific errors."""

    def test_missing_start_node(self, invalid_ckp_missing_start):
        ir = parse_ckp(invalid_ckp_missing_start)
        errors = validate_ir(ir)
        assert len(errors) > 0
        assert any("nonexistent_node" in e for e in errors)

    def test_dangling_next_node(self, invalid_ckp_dangling_ref):
        ir = parse_ckp(invalid_ckp_dangling_ref)
        errors = validate_ir(ir)
        assert len(errors) > 0
        assert any("does_not_exist" in e for e in errors)

    def test_missing_procedure_id(self):
        ckp = {
            "procedure_id": "",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "a",
                "nodes": {"a": {"type": "terminate"}},
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("procedure_id" in e.lower() for e in errors)

    def test_missing_version(self):
        ckp = {
            "procedure_id": "test",
            "version": "",
            "workflow_graph": {
                "start_node": "a",
                "nodes": {"a": {"type": "terminate"}},
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("version" in e.lower() for e in errors)

    def test_missing_start_node_value(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "",
                "nodes": {"a": {"type": "terminate"}},
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("start_node" in e.lower() for e in errors)

    def test_logic_rule_dangling_target(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "logic",
                "nodes": {
                    "logic": {
                        "type": "logic",
                        "rules": [
                            {"condition": "true", "next_node": "ghost"},
                        ],
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("ghost" in e for e in errors)

    def test_logic_default_dangling(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "logic",
                "nodes": {
                    "logic": {
                        "type": "logic",
                        "rules": [],
                        "default_next_node": "phantom",
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("phantom" in e for e in errors)

    def test_loop_body_dangling(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "loop",
                "nodes": {
                    "loop": {
                        "type": "loop",
                        "iterator": "items",
                        "body_node": "missing_body",
                        "next_node": "loop",
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("missing_body" in e for e in errors)

    def test_parallel_branch_dangling(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "par",
                "nodes": {
                    "par": {
                        "type": "parallel",
                        "branches": [
                            {"branch_id": "b1", "start_node": "nowhere"},
                        ],
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("start_node not found" in e for e in errors)

    def test_human_approval_dangling_targets(self):
        ckp = {
            "procedure_id": "test",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "ha",
                "nodes": {
                    "ha": {
                        "type": "human_approval",
                        "prompt": "approve?",
                        "on_approve": "missing_approve",
                        "on_reject": "missing_reject",
                    },
                },
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert any("missing_approve" in e for e in errors)
        assert any("missing_reject" in e for e in errors)

    def test_multiple_errors_collected(self):
        """Validator should collect all errors, not stop at first."""
        ckp = {
            "procedure_id": "",
            "version": "",
            "workflow_graph": {
                "start_node": "",
                "nodes": {},
            },
        }
        ir = parse_ckp(ckp)
        errors = validate_ir(ir)
        assert len(errors) >= 3  # missing procedure_id, version, start_node


class TestValidateWorkflowDispatchMode:
    def test_valid_step_workflow_dispatch_mode(self):
        ckp = {
            "procedure_id": "wf_mode_valid",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "seq",
                "nodes": {
                    "seq": {
                        "type": "sequence",
                        "agent": "web_agent",
                        "steps": [
                            {
                                "step_id": "s1",
                                "action": "external_workflow",
                                "workflow_dispatch_mode": "sync",
                            }
                        ],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        errors = validate_ir(parse_ckp(ckp))
        assert errors == []

    def test_invalid_step_workflow_dispatch_mode(self):
        ckp = {
            "procedure_id": "wf_mode_invalid",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "seq",
                "nodes": {
                    "seq": {
                        "type": "sequence",
                        "agent": "web_agent",
                        "steps": [
                            {
                                "step_id": "s1",
                                "action": "external_workflow",
                                "workflow_dispatch_mode": "blocking",
                            }
                        ],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        errors = validate_ir(parse_ckp(ckp))
        assert any("workflow_dispatch_mode" in e for e in errors)

    def test_invalid_global_workflow_dispatch_mode(self):
        ckp = {
            "procedure_id": "wf_mode_invalid_global",
            "version": "1.0.0",
            "global_config": {"workflow_dispatch_mode": "blocking"},
            "workflow_graph": {
                "start_node": "seq",
                "nodes": {
                    "seq": {
                        "type": "sequence",
                        "steps": [{"step_id": "s1", "action": "log", "message": "ok"}],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        errors = validate_ir(parse_ckp(ckp))
        assert any("global_config.workflow_dispatch_mode" in e for e in errors)
