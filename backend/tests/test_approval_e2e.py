"""End-to-end integration tests for human_approval node execution.

These tests exercise the FULL pipeline:
  1. First run: graph detects awaiting_approval → Approval row created, run=waiting_approval
  2. User approves:    __approval_decisions injected into run.input_vars_json
  3. Resume run:       graph routes via decision → terminate → run=completed

All tests use a real in-memory SQLite DB (created by conftest._create_test_tables)
and call execute_run directly — NO mocks on the graph execution path.
"""

from __future__ import annotations

import json
import uuid

import pytest

from app.db.engine import async_session
from app.db.models import Approval, Run, RunEvent, RunJob


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _make_approval_ckp(pid: str) -> dict:
    """Simple CKP with a single human_approval node."""
    return {
        "procedure_id": pid,
        "version": "1.0.0",
        "global_config": {},
        "variables_schema": {},
        "workflow_graph": {
            "start_node": "approve",
            "nodes": {
                "approve": {
                    "type": "human_approval",
                    "prompt": "Please approve this action",
                    "decision_type": "approve_reject",
                    "on_approve": "success_end",
                    "on_reject": "failure_end",
                    "on_timeout": "failure_end",
                },
                "success_end": {"type": "terminate", "status": "success"},
                "failure_end": {"type": "terminate", "status": "failed"},
            },
        },
    }


async def _setup_procedure_and_run(pid: str, input_vars: dict | None = None) -> str:
    """Creates a procedure + run in DB and returns the run_id."""
    from app.services import procedure_service, run_service
    from app.worker.enqueue import enqueue_run

    async with async_session() as db:
        # Upsert procedure (import_procedure handles duplicate procedure_id+version)
        try:
            await procedure_service.import_procedure(db, _make_approval_ckp(pid))
            await db.commit()
        except Exception:
            await db.rollback()

    async with async_session() as db:
        run = await run_service.create_run(
            db,
            procedure_id=pid,
            procedure_version="1.0.0",
            input_vars=input_vars or {},
        )
        enqueue_run(db, run.run_id)
        await db.commit()
        return run.run_id


# ─────────────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────────────


class TestApprovalNodeE2E:
    """Full pipeline: first execution, approval decision, resume."""

    @pytest.mark.asyncio
    async def test_first_run_creates_pending_approval(self):
        """execute_run on a fresh run with human_approval node must:
        - create an Approval row with status='pending'
        - set run.status = 'waiting_approval'
        - set run.last_node_id = 'approve'
        """
        from app.services.execution_service import execute_run

        pid = f"appr_e2e_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)

        # Execute run — this should pause at the approval node
        await execute_run(run_id, async_session)

        # Verify run state
        async with async_session() as db:
            run = await db.get(Run, run_id)
            assert run is not None, "Run should exist"
            assert run.status == "waiting_approval", (
                f"Expected run.status='waiting_approval', got '{run.status}'"
            )
            assert run.last_node_id == "approve", (
                f"Expected run.last_node_id='approve', got '{run.last_node_id}'"
            )

        # Verify approval was created
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approvals = result.scalars().all()
            assert len(approvals) == 1, (
                f"Expected exactly 1 Approval, got {len(approvals)}"
            )
            approval = approvals[0]
            assert approval.status == "pending", (
                f"Expected approval.status='pending', got '{approval.status}'"
            )
            assert approval.node_id == "approve", (
                f"Expected approval.node_id='approve', got '{approval.node_id}'"
            )
            assert approval.prompt == "Please approve this action"

    @pytest.mark.asyncio
    async def test_approval_run_emits_approval_requested_event(self):
        """After first execution, an 'approval_requested' RunEvent must exist."""
        from app.services.execution_service import execute_run

        pid = f"appr_evt_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)
        await execute_run(run_id, async_session)

        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(RunEvent)
                .where(RunEvent.run_id == run_id)
                .where(RunEvent.event_type == "approval_requested")
            )
            events = result.scalars().all()
            assert events, "Should have emitted 'approval_requested' event"
            evt = events[0]
            payload = json.loads(evt.payload_json) if evt.payload_json else {}
            assert "approval_id" in payload, (
                f"approval_requested event payload should contain approval_id; got {payload}"
            )

    @pytest.mark.asyncio
    async def test_approved_run_completes_successfully(self):
        """After approval decision 'approved', resume should complete run with status='completed'."""
        from app.services.execution_service import execute_run
        from app.worker.enqueue import requeue_run

        pid = f"appr_ok_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)

        # Phase 1: initial run (pauses waiting for approval)
        await execute_run(run_id, async_session)

        # Retrieve the approval
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approval = result.scalar_one_or_none()
            assert approval is not None, "Approval must exist after first run"
            approval_id = str(approval.approval_id)
            node_id = approval.node_id  # "approve"

        # Phase 2: simulate approval decision (what approvals.py does)
        async with async_session() as db:
            from app.services import run_service
            run = await db.get(Run, run_id)
            assert run is not None

            # Inject approval decision into input_vars (mirror approvals.py logic)
            current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
            decisions = current_input.get("__approval_decisions", {})
            decisions[node_id] = "approved"  # approval.status after submit_decision
            current_input["__approval_decisions"] = decisions
            run.input_vars_json = json.dumps(current_input)

            # Mark approval decided
            appr = await db.get(Approval, approval_id)
            appr.status = "approved"
            appr.decided_by = "test_user"

            # Reset run + requeue (mirror approvals.py submit_decision)
            await run_service.update_run_status(db, run_id, "created")
            await requeue_run(db, run_id, priority=10)
            await db.commit()

        # Phase 3: resume execution
        await execute_run(run_id, async_session)

        # Verify run completed
        async with async_session() as db:
            run = await db.get(Run, run_id)
            assert run.status == "completed", (
                f"Expected run.status='completed' after approval, got '{run.status}'"
            )

    @pytest.mark.asyncio
    async def test_rejected_run_fails(self):
        """After rejection, resume should complete with status='failed'."""
        from app.services.execution_service import execute_run
        from app.worker.enqueue import requeue_run

        pid = f"appr_rej_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)

        # Phase 1: initial run
        await execute_run(run_id, async_session)

        # Get approval node_id
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approval = result.scalar_one()
            node_id = approval.node_id

        # Phase 2: inject rejection decision
        async with async_session() as db:
            from app.services import run_service
            run = await db.get(Run, run_id)
            current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
            current_input.setdefault("__approval_decisions", {})[node_id] = "rejected"
            run.input_vars_json = json.dumps(current_input)
            await run_service.update_run_status(db, run_id, "created")
            await requeue_run(db, run_id)
            await db.commit()

        # Phase 3: resume
        await execute_run(run_id, async_session)

        async with async_session() as db:
            run = await db.get(Run, run_id)
            # failure_end has status="failed" so run should be "failed"
            assert run.status == "failed", (
                f"Expected run.status='failed' after rejection, got '{run.status}'"
            )

    @pytest.mark.asyncio
    async def test_second_new_run_also_creates_approval(self):
        """Running the same procedure a second time (new run) should ALSO pause for approval — 
        no shared state from the first run should interfere.
        """
        from app.services.execution_service import execute_run

        pid = f"appr_2nd_{_uid()}"

        # First run
        run_id_1 = await _setup_procedure_and_run(pid)
        await execute_run(run_id_1, async_session)

        # Second run (fresh run, same procedure)
        run_id_2 = await _setup_procedure_and_run(pid)
        await execute_run(run_id_2, async_session)

        # Both runs should be waiting_approval
        async with async_session() as db:
            run2 = await db.get(Run, run_id_2)
            assert run2.status == "waiting_approval", (
                f"Second run should also pause at approval, got status='{run2.status}'"
            )

        # Second run should have its own Approval row
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id_2)
            )
            approvals_2 = result.scalars().all()
            assert len(approvals_2) == 1, (
                f"Second run should have exactly 1 pending approval, got {len(approvals_2)}"
            )

    @pytest.mark.asyncio
    async def test_resume_does_not_create_duplicate_approval(self):
        """On resume execution, no duplicate Approval rows should be created."""
        from app.services.execution_service import execute_run
        from app.worker.enqueue import requeue_run

        pid = f"appr_dup_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)

        # First execution: pause at approval
        await execute_run(run_id, async_session)

        # Get approval
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approval = result.scalar_one()
            node_id = approval.node_id

        # Inject approval + requeue
        async with async_session() as db:
            from app.services import run_service
            run = await db.get(Run, run_id)
            current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
            current_input.setdefault("__approval_decisions", {})[node_id] = "approved"
            run.input_vars_json = json.dumps(current_input)
            await run_service.update_run_status(db, run_id, "created")
            await requeue_run(db, run_id, priority=10)
            await db.commit()

        # Resume execution
        await execute_run(run_id, async_session)

        # Should still be only 1 approval row
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approvals = result.scalars().all()
            assert len(approvals) == 1, (
                f"Resume should not create duplicate approvals; found {len(approvals)}"
            )

    @pytest.mark.asyncio
    async def test_input_vars_saved_correctly_at_pause(self):
        """When run pauses, input_vars_json should NOT contain double-underscore system keys."""
        from app.services.execution_service import execute_run

        pid = f"appr_vars_{_uid()}"
        run_id = await _setup_procedure_and_run(pid, input_vars={"user_key": "user_value"})
        await execute_run(run_id, async_session)

        async with async_session() as db:
            run = await db.get(Run, run_id)
            assert run.status == "waiting_approval"
            saved = json.loads(run.input_vars_json) if run.input_vars_json else {}
            # user keys should be preserved
            assert saved.get("user_key") == "user_value", (
                f"user_key should be preserved in saved vars; got {saved}"
            )
            # __approval_decisions should NOT be present at pause time
            # (it's added AFTER the user makes a decision in approvals.py)
            assert "__approval_decisions" not in saved, (
                f"__approval_decisions should not be in saved_vars at pause; got {saved}"
            )

    @pytest.mark.asyncio
    async def test_approval_decisions_injected_before_resume(self):
        """After approval decision injection, __approval_decisions should appear in input_vars_json."""
        from app.services.execution_service import execute_run
        from app.worker.enqueue import requeue_run

        pid = f"appr_inj_{_uid()}"
        run_id = await _setup_procedure_and_run(pid)
        await execute_run(run_id, async_session)

        # Get node_id
        async with async_session() as db:
            from sqlalchemy import select
            result = await db.execute(
                select(Approval).where(Approval.run_id == run_id)
            )
            approval = result.scalar_one()
            node_id = approval.node_id

        # Inject decision (simulates approvals.py/submit_decision)
        async with async_session() as db:
            from app.services import run_service
            run = await db.get(Run, run_id)
            current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
            current_input.setdefault("__approval_decisions", {})[node_id] = "approved"
            run.input_vars_json = json.dumps(current_input)
            await run_service.update_run_status(db, run_id, "created")
            await requeue_run(db, run_id, priority=10)
            await db.commit()

        # Verify __approval_decisions is now in input_vars_json
        async with async_session() as db:
            run = await db.get(Run, run_id)
            stored = json.loads(run.input_vars_json) if run.input_vars_json else {}
            assert "__approval_decisions" in stored, (
                "__approval_decisions should be in input_vars_json after decision injection"
            )
            assert stored["__approval_decisions"].get(node_id) == "approved", (
                f"Decision should be 'approved' for node '{node_id}'"
            )
