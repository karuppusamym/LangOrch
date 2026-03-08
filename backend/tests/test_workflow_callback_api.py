"""Regression tests for workflow callback hardening behavior."""

from __future__ import annotations

import hashlib
import hmac
import uuid

import pytest
from fastapi import BackgroundTasks, HTTPException
from unittest.mock import AsyncMock, MagicMock, patch

from app.api.runs import workflow_callback
from app.config import settings
from app.db.engine import async_session
from app.services import run_service
from app.services.run_service import auto_fail_stalled_workflows


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _token(run_id: str) -> str:
    return hmac.new(
        settings.AUTH_SECRET_KEY.encode(),
        run_id.encode(),
        hashlib.sha256,
    ).hexdigest()


async def _make_paused_run() -> str:
    async with async_session() as db:
        run = await run_service.create_run(
            db,
            procedure_id=f"cb_proc_{_uid()}",
            procedure_version="1.0.0",
            input_vars={},
        )
        await run_service.update_run_status(db, run.run_id, "paused")
        await db.commit()
        return run.run_id


class TestWorkflowCallbackHardening:
    @pytest.mark.asyncio
    async def test_duplicate_callback_is_ignored(self):
        run_id = await _make_paused_run()

        async with async_session() as db:
            await run_service.emit_event(
                db,
                run_id,
                "workflow_delegated",
                node_id="node-1",
                step_id="step-1",
                payload={"resume_node_id": "node-1", "resume_step_id": "step-1"},
            )
            await db.commit()

        async with async_session() as db:
            first = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                    "output": {"a": 1},
                },
                background_tasks=BackgroundTasks(),
                token=_token(run_id),
                db=db,
            )
            assert first["resumed"] is True

        async with async_session() as db:
            second = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                    "output": {"a": 1},
                },
                background_tasks=BackgroundTasks(),
                token=_token(run_id),
                db=db,
            )
            assert second["resumed"] is False
            assert second["status"] == "duplicate"

    @pytest.mark.asyncio
    async def test_callback_rejects_mismatched_node_step(self):
        run_id = await _make_paused_run()

        async with async_session() as db:
            await run_service.emit_event(
                db,
                run_id,
                "workflow_delegated",
                node_id="expected-node",
                step_id="expected-step",
                payload={
                    "resume_node_id": "expected-node",
                    "resume_step_id": "expected-step",
                },
            )
            await db.commit()

        async with async_session() as db:
            with pytest.raises(HTTPException) as exc_info:
                await workflow_callback(
                    run_id=run_id,
                    body={
                        "status": "success",
                        "node_id": "wrong-node",
                        "step_id": "expected-step",
                    },
                    background_tasks=BackgroundTasks(),
                    token=_token(run_id),
                    db=db,
                )
            assert exc_info.value.status_code == 400
            assert "does not match expected" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_late_callback_for_terminal_run_is_acknowledged(self):
        async with async_session() as db:
            run = await run_service.create_run(
                db,
                procedure_id=f"cb_proc_{_uid()}",
                procedure_version="1.0.0",
                input_vars={},
            )
            await run_service.update_run_status(db, run.run_id, "failed")
            await db.commit()
            run_id = run.run_id

        async with async_session() as db:
            late = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                },
                background_tasks=BackgroundTasks(),
                token=_token(run_id),
                db=db,
            )
            assert late["resumed"] is False
            assert late["status"] == "failed"

    @pytest.mark.asyncio
    async def test_late_callback_for_canceled_run_is_acknowledged(self):
        async with async_session() as db:
            run = await run_service.create_run(
                db,
                procedure_id=f"cb_proc_{_uid()}",
                procedure_version="1.0.0",
                input_vars={},
            )
            await run_service.update_run_status(db, run.run_id, "canceled")
            await db.commit()
            run_id = run.run_id

        async with async_session() as db:
            late = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                },
                background_tasks=BackgroundTasks(),
                token=_token(run_id),
                db=db,
            )
            assert late["resumed"] is False
            assert late["status"] == "canceled"

    @pytest.mark.asyncio
    async def test_timeout_sweeper_skips_run_with_callback_event(self):
        run_id = await _make_paused_run()

        async with async_session() as db:
            await run_service.emit_event(
                db,
                run_id,
                "workflow_delegated",
                node_id="node-1",
                step_id="step-1",
                payload={"resume_node_id": "node-1", "resume_step_id": "step-1"},
            )
            await run_service.emit_event(
                db,
                run_id,
                "workflow_callback_received",
                node_id="node-1",
                step_id="step-1",
                payload={"status": "success"},
            )
            await db.commit()

        async with async_session() as db:
            failed_runs = await auto_fail_stalled_workflows(db, timeout_minutes=0)
            run = await run_service.get_run(db, run_id)

            assert run is not None
            assert run.status == "paused"
            assert run_id not in failed_runs

    @pytest.mark.asyncio
    async def test_duplicate_callback_losing_atomic_race_is_ignored(self):
        run_id = f"run-{_uid()}"

        paused_run = MagicMock()
        paused_run.run_id = run_id
        paused_run.status = "paused"

        queued_run = MagicMock()
        queued_run.run_id = run_id
        queued_run.status = "queued"

        empty_result = MagicMock()
        empty_result.scalar_one_or_none.return_value = None

        transition_result = MagicMock()
        transition_result.rowcount = 0

        current_run_result = MagicMock()
        current_run_result.scalar_one_or_none.return_value = queued_run

        callback_marker_result = MagicMock()
        callback_marker_result.scalar_one_or_none.return_value = 123

        db = AsyncMock()
        db.execute = AsyncMock(
            side_effect=[
                empty_result,
                empty_result,
                transition_result,
                current_run_result,
                callback_marker_result,
            ]
        )

        with patch("app.services.run_service.get_run", new=AsyncMock(return_value=paused_run)):
            result = await workflow_callback(
                run_id=run_id,
                body={
                    "status": "success",
                    "node_id": "node-1",
                    "step_id": "step-1",
                    "output": {"a": 1},
                },
                background_tasks=BackgroundTasks(),
                token=_token(run_id),
                db=db,
            )

        assert result["resumed"] is False
        assert result["status"] == "duplicate"
        db.commit.assert_not_awaited()
