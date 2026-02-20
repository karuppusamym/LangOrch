"""Batch 24 integration tests — parallel branch execution, checkpoint resume IR,
approval decision flow, subflow execution, and LLM usage event structure.

Coverage:
  1. Parallel branch execution — parse + bind CKP with parallel node; verify IR
  2. Checkpoint resume IR — parse + bind CKP with is_checkpoint nodes; verify flags
  3. Approval decision flow — service-level create / submit_decision / expire logic
  4. Subflow execution — parse + bind CKP with subflow node; verify IRSubflowPayload
  5. LLM usage event structure — llm_usage event payload keys
"""

from __future__ import annotations

import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


def _parse_and_bind(ckp: dict):
    """Parse a CKP dict through the full compiler pipeline and return (ir, errors)."""
    from app.compiler.parser import parse_ckp
    from app.compiler.binder import bind_executors
    from app.compiler.validator import validate_ir

    ir = parse_ckp(ckp)
    ir = bind_executors(ir)
    errors = validate_ir(ir)
    return ir, errors


def _make_parallel_ckp(wait_strategy: str = "all") -> dict:
    return {
        "procedure_id": "par_proc",
        "version": "1.0.0",
        "global_config": {"max_retries": 0},
        "workflow_graph": {
            "start_node": "par",
            "nodes": {
                "par": {
                    "type": "parallel",
                    "branches": [
                        {"branch_id": "b1", "start_node": "branch1"},
                        {"branch_id": "b2", "start_node": "branch2"},
                        {"branch_id": "b3", "start_node": "branch3"},
                    ],
                    "wait_strategy": wait_strategy,
                    "next_node": "finish",
                },
                "branch1": {
                    "type": "sequence",
                    "steps": [{"step_id": "s1", "action": "log", "message": "b1"}],
                    "next_node": "finish",
                },
                "branch2": {
                    "type": "sequence",
                    "steps": [{"step_id": "s2", "action": "log", "message": "b2"}],
                    "next_node": "finish",
                },
                "branch3": {
                    "type": "sequence",
                    "steps": [{"step_id": "s3", "action": "set_variable", "variable": "x", "value": 1}],
                    "next_node": "finish",
                },
                "finish": {"type": "terminate", "status": "success"},
            },
        },
    }


def _make_checkpoint_ckp() -> dict:
    return {
        "procedure_id": "ckp_proc",
        "version": "1.0.0",
        "global_config": {
            "max_retries": 1,
            "checkpoint_strategy": "always",
        },
        "workflow_graph": {
            "start_node": "init",
            "nodes": {
                "init": {
                    "type": "sequence",
                    "is_checkpoint": True,
                    "steps": [{"step_id": "s1", "action": "log", "message": "start"}],
                    "next_node": "middle",
                },
                "middle": {
                    "type": "sequence",
                    "is_checkpoint": True,
                    "steps": [{"step_id": "s2", "action": "set_variable", "variable": "done", "value": True}],
                    "next_node": "end",
                },
                "end": {
                    "type": "terminate",
                    "status": "success",
                    "is_checkpoint": False,
                },
            },
        },
    }


def _make_subflow_ckp(child_id: str = "child_proc") -> dict:
    return {
        "procedure_id": "parent_proc",
        "version": "1.0.0",
        "workflow_graph": {
            "start_node": "sub",
            "nodes": {
                "sub": {
                    "type": "subflow",
                    "procedure_id": child_id,
                    "version": "1.0.0",
                    "input_mapping": {"parent_x": "child_x"},
                    "output_mapping": {"child_y": "parent_y"},
                    "next_node": "done",
                },
                "done": {"type": "terminate", "status": "success"},
            },
        },
    }


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 1. Parallel branch execution
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestParallelBranchExecution:
    """CKP with parallel node parses + binds cleanly, IR reflects all branches."""

    def test_parallel_node_type(self):
        """Parallel node is parsed as type='parallel' in IR."""
        ir, _ = _parse_and_bind(_make_parallel_ckp())
        assert ir.nodes["par"].type == "parallel"

    def test_parallel_payload_has_branches(self):
        """IRParallelPayload records all branches declared in CKP."""
        from app.compiler.ir import IRParallelPayload
        ir, _ = _parse_and_bind(_make_parallel_ckp())
        payload = ir.nodes["par"].payload
        assert isinstance(payload, IRParallelPayload)
        branch_ids = [b.branch_id for b in payload.branches]
        assert "b1" in branch_ids
        assert "b2" in branch_ids
        assert "b3" in branch_ids

    def test_parallel_wait_strategy_propagated(self):
        """wait_strategy from CKP is preserved in IRParallelPayload."""
        from app.compiler.ir import IRParallelPayload
        ir, _ = _parse_and_bind(_make_parallel_ckp(wait_strategy="any"))
        payload = ir.nodes["par"].payload
        assert isinstance(payload, IRParallelPayload)
        assert payload.wait_strategy == "any"

    def test_parallel_branch_nodes_reachable(self):
        """All branch start nodes are present in IR.nodes (reachable)."""
        ir, errors = _parse_and_bind(_make_parallel_ckp())
        # No validation errors
        assert not errors
        # All branch nodes are in IR
        assert "branch1" in ir.nodes
        assert "branch2" in ir.nodes
        assert "branch3" in ir.nodes

    def test_parallel_validates_cleanly(self):
        """Full parallel CKP has zero validation errors."""
        _, errors = _parse_and_bind(_make_parallel_ckp())
        assert errors == []

    def test_parallel_next_node_preserved(self):
        """parallel node's next_node is preserved in payload."""
        from app.compiler.ir import IRParallelPayload
        ir, _ = _parse_and_bind(_make_parallel_ckp())
        payload = ir.nodes["par"].payload
        assert isinstance(payload, IRParallelPayload)
        assert payload.next_node_id == "finish"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 2. Checkpoint resume IR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestCheckpointResumeIR:
    """is_checkpoint flags parsed from CKP are faithfully reflected in IR."""

    def test_checkpoint_flag_set_on_marked_nodes(self):
        """Nodes with is_checkpoint=True have is_checkpoint=True in IR."""
        ir, _ = _parse_and_bind(_make_checkpoint_ckp())
        assert ir.nodes["init"].is_checkpoint is True
        assert ir.nodes["middle"].is_checkpoint is True

    def test_checkpoint_flag_absent_on_unmarked_nodes(self):
        """Nodes without is_checkpoint default to False in IR."""
        ir, _ = _parse_and_bind(_make_checkpoint_ckp())
        assert ir.nodes["end"].is_checkpoint is False

    def test_checkpoint_strategy_in_global_config(self):
        """checkpoint_strategy field is parsed into IR's global_config."""
        ir, _ = _parse_and_bind(_make_checkpoint_ckp())
        cfg = ir.global_config or {}
        assert cfg.get("checkpoint_strategy") == "always"

    def test_checkpoint_none_strategy_ckp(self):
        """checkpoint_strategy='none' is accepted and stored."""
        ckp = _make_checkpoint_ckp()
        ckp["global_config"]["checkpoint_strategy"] = "none"
        ir, errors = _parse_and_bind(ckp)
        assert not errors
        cfg = ir.global_config or {}
        assert cfg.get("checkpoint_strategy") == "none"

    def test_multiple_checkpoint_nodes_validate(self):
        """CKP with multiple is_checkpoint nodes passes validation."""
        _, errors = _parse_and_bind(_make_checkpoint_ckp())
        assert errors == []


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 3. Approval decision flow
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestApprovalDecisionFlow:
    """Approval service logic: create, list, decide, expire."""

    def _mock_approval(
        self,
        status: str = "pending",
        expires_at: datetime | None = None,
    ):
        """Build a mock Approval ORM object."""
        a = MagicMock()
        a.approval_id = str(uuid.uuid4())
        a.run_id = "run-abc"
        a.node_id = "approval_node"
        a.prompt = "Please review"
        a.decision_type = "approve_reject"
        a.status = status
        a.expires_at = expires_at
        a.decided_by = None
        a.decided_at = None
        a.options_json = None
        a.context_data_json = None
        a.created_at = datetime.now(timezone.utc)
        return a

    def test_submit_decision_mutates_status(self):
        """submit_decision sets approval.status to the given decision."""
        import asyncio
        from app.services import approval_service

        approval_obj = self._mock_approval()
        db = AsyncMock()
        db.get = AsyncMock(return_value=approval_obj)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        import asyncio as _asyncio
        _asyncio.run(
            approval_service.submit_decision(db, approval_obj.approval_id, "approved", decided_by="alice")
        )
        assert approval_obj.status == "approved"
        assert approval_obj.decided_by == "alice"

    def test_submit_decision_rejected(self):
        """submit_decision works for 'rejected' decision."""
        import asyncio as _asyncio
        from app.services import approval_service

        approval_obj = self._mock_approval()
        db = AsyncMock()
        db.get = AsyncMock(return_value=approval_obj)
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        _asyncio.run(
            approval_service.submit_decision(db, approval_obj.approval_id, "rejected", decided_by="bob")
        )
        assert approval_obj.status == "rejected"
        assert approval_obj.decided_by == "bob"

    def test_submit_decision_ignores_non_pending(self):
        """submit_decision returns None if approval is already decided."""
        import asyncio as _asyncio
        from app.services import approval_service

        approval_obj = self._mock_approval(status="approved")
        db = AsyncMock()
        db.get = AsyncMock(return_value=approval_obj)

        result = _asyncio.run(
            approval_service.submit_decision(db, approval_obj.approval_id, "rejected")
        )
        assert result is None

    def test_submit_decision_missing_approval(self):
        """submit_decision returns None when approval_id does not exist."""
        import asyncio as _asyncio
        from app.services import approval_service

        db = AsyncMock()
        db.get = AsyncMock(return_value=None)

        result = _asyncio.run(
            approval_service.submit_decision(db, "nonexistent-id", "approved")
        )
        assert result is None

    def test_create_approval_sets_expires_at(self):
        """create_approval calculates expires_at from timeout_ms."""
        import asyncio
        from app.services import approval_service

        created_approval = MagicMock()
        db = AsyncMock()
        db.add = MagicMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()

        # We test the logic by calling and inspecting what was added to db
        captured = {}

        def capture_add(obj):
            captured["obj"] = obj

        db.add = capture_add

        import asyncio as _asyncio
        _asyncio.run(
            approval_service.create_approval(
                db,
                run_id="run1",
                node_id="node1",
                prompt="Approve?",
                decision_type="approve_reject",
                timeout_ms=60_000,
            )
        )
        obj = captured["obj"]
        assert obj.expires_at is not None
        # expires_at should be ~60 seconds in the future
        diff = (obj.expires_at - datetime.now(timezone.utc)).total_seconds()
        assert 55 < diff < 65

    def test_create_approval_no_timeout(self):
        """create_approval with no timeout_ms leaves expires_at as None."""
        import asyncio
        from app.services import approval_service

        db = AsyncMock()
        db.flush = AsyncMock()
        db.refresh = AsyncMock()
        captured = {}

        def capture_add(obj):
            captured["obj"] = obj

        db.add = capture_add

        import asyncio as _asyncio
        _asyncio.run(
            approval_service.create_approval(
                db,
                run_id="run1",
                node_id="node1",
                prompt="Approve?",
                decision_type="approve_reject",
            )
        )
        assert captured["obj"].expires_at is None


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 4. Subflow execution IR
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestSubflowExecution:
    """Subflow nodes parse to IRSubflowPayload with correct linkage."""

    def test_subflow_node_type(self):
        """Subflow node is parsed as type='subflow' in IR."""
        ir, _ = _parse_and_bind(_make_subflow_ckp())
        assert ir.nodes["sub"].type == "subflow"

    def test_subflow_payload_procedure_id(self):
        """IRSubflowPayload.procedure_id matches child_proc."""
        from app.compiler.ir import IRSubflowPayload
        ir, _ = _parse_and_bind(_make_subflow_ckp(child_id="child_proc"))
        payload = ir.nodes["sub"].payload
        assert isinstance(payload, IRSubflowPayload)
        assert payload.procedure_id == "child_proc"

    def test_subflow_payload_input_mapping(self):
        """IRSubflowPayload.input_mapping reflects the CKP mapping."""
        from app.compiler.ir import IRSubflowPayload
        ir, _ = _parse_and_bind(_make_subflow_ckp())
        payload = ir.nodes["sub"].payload
        assert isinstance(payload, IRSubflowPayload)
        assert payload.input_mapping == {"parent_x": "child_x"}

    def test_subflow_payload_output_mapping(self):
        """IRSubflowPayload.output_mapping reflects the CKP mapping."""
        from app.compiler.ir import IRSubflowPayload
        ir, _ = _parse_and_bind(_make_subflow_ckp())
        payload = ir.nodes["sub"].payload
        assert isinstance(payload, IRSubflowPayload)
        assert payload.output_mapping == {"child_y": "parent_y"}

    def test_subflow_validates_cleanly(self):
        """Subflow CKP with a different child_proc_id has zero validation errors."""
        _, errors = _parse_and_bind(_make_subflow_ckp(child_id="external_proc"))
        assert errors == []

    def test_subflow_self_reference_detected(self):
        """Validator catches direct self-recursion in a subflow node."""
        _, errors = _parse_and_bind(_make_subflow_ckp(child_id="parent_proc"))
        assert any("self-recursion" in e.lower() or "infinite loop" in e.lower() for e in errors)

    def test_subflow_next_node_preserved(self):
        """IRSubflowPayload.next_node_id preserved from CKP."""
        from app.compiler.ir import IRSubflowPayload
        ir, _ = _parse_and_bind(_make_subflow_ckp())
        payload = ir.nodes["sub"].payload
        assert isinstance(payload, IRSubflowPayload)
        assert payload.next_node_id == "done"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# 5. LLM usage event structure
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━


class TestLlmUsageEventStructure:
    """llm_usage event emitted during execute_llm_action has correct payload keys."""

    def test_llm_usage_event_emitted(self):
        """execute_llm_action source contains run_service import and llm_usage event emission."""
        import inspect
        from app.runtime import node_executors

        src = inspect.getsource(node_executors.execute_llm_action)
        # The fix: run_service must be locally imported inside execute_llm_action
        assert "run_service" in src, "run_service must be referenced in execute_llm_action"
        assert '"llm_usage"' in src, 'llm_usage event must be emitted in execute_llm_action'
        assert '"prompt_tokens"' in src
        assert '"completion_tokens"' in src
        # Verify the local import is present (fixes the 'run_service not defined' bug)
        assert "from app.services import run_service" in src

    def test_llm_usage_event_keys(self):
        """llm_usage event payload always includes model, prompt_tokens, completion_tokens."""
        # Structural check: the token tracking block in node_executors uses these exact keys
        import inspect
        from app.runtime import node_executors
        src = inspect.getsource(node_executors)
        assert '"llm_usage"' in src
        assert '"prompt_tokens"' in src
        assert '"completion_tokens"' in src
        assert '"total_tokens"' in src

    def test_model_cost_table_covers_expected_models(self):
        """_MODEL_COST_PER_1K includes all common models used in LLM actions."""
        from app.runtime.node_executors import _MODEL_COST_PER_1K
        expected = ["gpt-4", "gpt-4o", "gpt-3.5-turbo", "claude-3-sonnet"]
        for model in expected:
            assert model in _MODEL_COST_PER_1K, f"{model!r} missing from _MODEL_COST_PER_1K"
