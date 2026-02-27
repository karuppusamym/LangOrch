"""Tests for CKP parser — parse_ckp function and all node type parsers."""

from __future__ import annotations

import pytest

from app.compiler.parser import parse_ckp
from app.compiler.ir import (
    ExecutorBinding,
    IRHumanApprovalPayload,
    IRLlmActionPayload,
    IRLogicPayload,
    IRLoopPayload,
    IRNode,
    IRParallelPayload,
    IRProcessingPayload,
    IRProcedure,
    IRSequencePayload,
    IRSubflowPayload,
    IRTerminatePayload,
    IRTransformPayload,
    IRVerificationPayload,
)


# ── Top-level parsing ───────────────────────────────────────────


class TestParseTopLevel:
    def test_procedure_id_and_version(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        assert ir.procedure_id == "test_proc"
        assert ir.version == "1.0.0"

    def test_global_config_preserved(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        assert ir.global_config["max_retries"] == 2
        assert ir.global_config["retry_delay_ms"] == 500

    def test_variables_schema_preserved(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        assert "greeting" in ir.variables_schema
        assert ir.variables_schema["greeting"]["default"] == "hello"

    def test_start_node_id(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        assert ir.start_node_id == "start"

    def test_nodes_parsed(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        assert "start" in ir.nodes
        assert "end" in ir.nodes
        assert len(ir.nodes) == 2

    def test_empty_global_config_defaults(self):
        ckp = {
            "procedure_id": "p",
            "version": "1.0",
            "workflow_graph": {"start_node": "a", "nodes": {"a": {"type": "terminate"}}},
        }
        ir = parse_ckp(ckp)
        assert ir.global_config == {}
        assert ir.variables_schema == {}

    def test_complex_ckp_node_count(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        assert len(ir.nodes) == 6
        assert ir.nodes["init"].type == "sequence"
        assert ir.nodes["decide"].type == "logic"
        assert ir.nodes["process"].type == "loop"
        assert ir.nodes["finish"].type == "terminate"


# ── Sequence node parsing ───────────────────────────────────────


class TestParseSequence:
    def test_steps_parsed(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        payload = ir.nodes["start"].payload
        assert isinstance(payload, IRSequencePayload)
        assert len(payload.steps) == 1
        assert payload.steps[0].step_id == "log_hello"
        assert payload.steps[0].action == "log"

    def test_step_params_extracted(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        step = ir.nodes["start"].payload.steps[0]
        assert step.params.get("message") == "Hello from test"

    def test_multiple_steps(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["init"].payload
        assert isinstance(payload, IRSequencePayload)
        assert len(payload.steps) == 2
        assert payload.steps[0].action == "log"
        assert payload.steps[1].action == "set_variable"

    def test_node_metadata(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        node = ir.nodes["init"]
        assert node.agent == "MasterAgent"
        assert node.next_node_id == "decide"
        assert node.is_checkpoint is True


# ── Logic node parsing ──────────────────────────────────────────


class TestParseLogic:
    def test_logic_rules(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["decide"].payload
        assert isinstance(payload, IRLogicPayload)
        assert len(payload.rules) == 2
        assert payload.rules[0].condition_expr == "vars.x > 5"
        assert payload.rules[0].next_node_id == "process"

    def test_logic_default_node(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["decide"].payload
        assert payload.default_next_node_id == "skip"


# ── Loop node parsing ───────────────────────────────────────────


class TestParseLoop:
    def test_loop_fields(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["process"].payload
        assert isinstance(payload, IRLoopPayload)
        assert payload.iterator_var == "items"
        assert payload.iterator_variable == "current_item"
        assert payload.body_node_id == "loop_body"
        assert payload.next_node_id == "finish"
        assert payload.max_iterations == 100


# ── Parallel node parsing ───────────────────────────────────────


class TestParseParallel:
    def test_parallel_branches(self, ckp_with_parallel):
        ir = parse_ckp(ckp_with_parallel)
        payload = ir.nodes["par"].payload
        assert isinstance(payload, IRParallelPayload)
        assert len(payload.branches) == 2
        assert payload.branches[0].branch_id == "b1"
        assert payload.branches[0].start_node_id == "branch1"
        assert payload.wait_strategy == "all"

    def test_parallel_next_node(self, ckp_with_parallel):
        ir = parse_ckp(ckp_with_parallel)
        payload = ir.nodes["par"].payload
        assert payload.next_node_id == "end"


# ── Human approval node parsing ─────────────────────────────────


class TestParseHumanApproval:
    def test_approval_fields(self, ckp_with_human_approval):
        ir = parse_ckp(ckp_with_human_approval)
        payload = ir.nodes["approval"].payload
        assert isinstance(payload, IRHumanApprovalPayload)
        assert payload.prompt == "Do you approve?"
        assert payload.decision_type == "approve_reject"
        assert payload.on_approve == "approved"
        assert payload.on_reject == "rejected"
        assert payload.on_timeout == "timeout"
        assert payload.timeout_ms == 5000


# ── LLM action node parsing ─────────────────────────────────────


class TestParseLlmAction:
    def test_llm_fields(self, ckp_with_llm_action):
        ir = parse_ckp(ckp_with_llm_action)
        payload = ir.nodes["llm_step"].payload
        assert isinstance(payload, IRLlmActionPayload)
        assert payload.prompt == "Summarize the document"
        assert payload.model == "gpt-4"
        assert payload.temperature == 0.5
        assert payload.max_tokens == 1000

    def test_llm_attachments(self, ckp_with_llm_action):
        ir = parse_ckp(ckp_with_llm_action)
        payload = ir.nodes["llm_step"].payload
        assert len(payload.attachments) == 1
        assert payload.attachments[0].type == "file"
        assert payload.attachments[0].source == "document.pdf"

    def test_llm_outputs(self, ckp_with_llm_action):
        ir = parse_ckp(ckp_with_llm_action)
        payload = ir.nodes["llm_step"].payload
        assert payload.outputs == {"summary": "summary_var"}


# ── Transform node parsing ──────────────────────────────────────


class TestParseTransform:
    def test_transform_operations(self, ckp_with_transform):
        ir = parse_ckp(ckp_with_transform)
        payload = ir.nodes["transform"].payload
        assert isinstance(payload, IRTransformPayload)
        assert len(payload.transformations) == 1
        t = payload.transformations[0]
        assert t.type == "map"
        assert t.source_variable == "items"
        assert t.expression == "item.name"
        assert t.output_variable == "names"


# ── Subflow node parsing ────────────────────────────────────────


class TestParseSubflow:
    def test_subflow_fields(self, ckp_with_subflow):
        ir = parse_ckp(ckp_with_subflow)
        payload = ir.nodes["sub"].payload
        assert isinstance(payload, IRSubflowPayload)
        assert payload.procedure_id == "child_proc"
        assert payload.version == "1.0.0"
        assert payload.input_mapping == {"parent_var": "child_var"}
        assert payload.output_mapping == {"child_result": "parent_result"}
        assert payload.on_failure == "fail_parent"
        assert payload.next_node_id == "end"


# ── Terminate node parsing ──────────────────────────────────────


class TestParseTerminate:
    def test_terminate_status(self, minimal_ckp):
        ir = parse_ckp(minimal_ckp)
        payload = ir.nodes["end"].payload
        assert isinstance(payload, IRTerminatePayload)
        assert payload.status == "success"

    def test_terminate_with_outputs(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["finish"].payload
        assert isinstance(payload, IRTerminatePayload)
        assert payload.outputs == {"result": "done"}


# ── Processing node parsing ─────────────────────────────────────


class TestParseProcessing:
    def test_processing_operations(self, complex_ckp):
        ir = parse_ckp(complex_ckp)
        payload = ir.nodes["skip"].payload
        assert isinstance(payload, IRProcessingPayload)
        assert len(payload.operations) == 1
        assert payload.operations[0].action == "log"
        assert payload.next_node_id == "finish"


# ── Verification node parsing ───────────────────────────────────


class TestParseVerification:
    def test_verification_checks(self):
        ckp = {
            "procedure_id": "ver_proc",
            "version": "1.0.0",
            "workflow_graph": {
                "start_node": "ver",
                "nodes": {
                    "ver": {
                        "type": "verification",
                        "checks": [
                            {
                                "id": "c1",
                                "condition": "vars.x > 0",
                                "on_fail": "fail_workflow",
                                "message": "x must be positive",
                            }
                        ],
                        "next_node": "end",
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        ir = parse_ckp(ckp)
        payload = ir.nodes["ver"].payload
        assert isinstance(payload, IRVerificationPayload)
        assert len(payload.checks) == 1
        assert payload.checks[0].id == "c1"
        assert payload.checks[0].condition == "vars.x > 0"
        assert payload.checks[0].on_fail == "fail_workflow"
        assert payload.checks[0].message == "x must be positive"


class TestParseWorkflowDispatchMode:
    def test_step_workflow_dispatch_mode_parsed(self):
        ckp = {
            "procedure_id": "wf_mode_proc",
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
        ir = parse_ckp(ckp)
        step = ir.nodes["seq"].payload.steps[0]
        assert step.workflow_dispatch_mode == "sync"

    def test_global_workflow_dispatch_mode_preserved(self):
        ckp = {
            "procedure_id": "wf_mode_global_proc",
            "version": "1.0.0",
            "global_config": {"workflow_dispatch_mode": "async"},
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
        ir = parse_ckp(ckp)
        assert ir.global_config["workflow_dispatch_mode"] == "async"
