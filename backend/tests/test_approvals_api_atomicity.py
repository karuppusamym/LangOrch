from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.api import approvals as approvals_api
from app.api.auth import _issue_jwt
from app.config import settings
from app.db.engine import async_session
from app.db.models import Approval, Run, RunEvent
from app.main import app


def _uid() -> str:
    return uuid.uuid4().hex[:8]


def _auth_headers(role: str) -> dict[str, str]:
    token = _issue_jwt(f"test-{role}", [role], 60, settings.AUTH_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


def _make_approval_ckp(pid: str) -> dict:
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


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "approvals-test-secret-with-at-least-32-bytes")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


async def _create_waiting_approval_run() -> tuple[str, str, str]:
    from app.services import procedure_service, run_service
    from app.services.execution_service import execute_run

    pid = f"approval_api_{_uid()}"

    async with async_session() as db:
        await procedure_service.import_procedure(db, _make_approval_ckp(pid))
        await db.commit()

    async with async_session() as db:
        run = await run_service.create_run(
            db,
            procedure_id=pid,
            procedure_version="1.0.0",
            input_vars={},
        )
        await db.commit()
        run_id = run.run_id

    await execute_run(run_id, async_session)

    async with async_session() as db:
        result = await db.execute(select(Approval).where(Approval.run_id == run_id))
        approval = result.scalar_one()
        return run_id, str(approval.approval_id), approval.node_id


class TestApprovalsApiAtomicity:
    @pytest.mark.asyncio
    async def test_submit_decision_accepts_resolved_decision_payload(self, client):
        run_id, approval_id, node_id = await _create_waiting_approval_run()

        response = await client.post(
            f"/api/approvals/{approval_id}/decision",
            json={"resolved_decision": "approve", "decided_by": "tester"},
            headers=_auth_headers("approver"),
        )

        assert response.status_code == 200
        assert response.json()["status"] == "approved"

        async with async_session() as db:
            approval = await db.get(Approval, approval_id)
            run = await db.get(Run, run_id)
            assert approval is not None
            assert approval.status == "approved"
            assert approval.decided_by == "tester"
            assert run is not None
            assert run.status == "created"
            stored_input = json.loads(run.input_vars_json or "{}")
            assert stored_input["__approval_decisions"][node_id] == "approved"

    @pytest.mark.asyncio
    async def test_submit_decision_rolls_back_when_requeue_fails(self, client, monkeypatch):
        run_id, approval_id, _node_id = await _create_waiting_approval_run()
        monkeypatch.setattr(
            approvals_api,
            "requeue_run",
            AsyncMock(side_effect=RuntimeError("queue unavailable")),
        )

        response = await client.post(
            f"/api/approvals/{approval_id}/decision",
            json={"resolved_decision": "approve", "decided_by": "tester"},
            headers=_auth_headers("approver"),
        )

        assert response.status_code == 500
        assert response.json()["detail"] == "Failed to resume run after approval decision"

        async with async_session() as db:
            approval = await db.get(Approval, approval_id)
            run = await db.get(Run, run_id)
            events = await db.execute(
                select(RunEvent).where(
                    RunEvent.run_id == run_id,
                    RunEvent.event_type == "approval_decision_received",
                )
            )

            assert approval is not None
            assert approval.status == "pending"
            assert approval.decided_by is None
            assert approval.decided_at is None

            assert run is not None
            assert run.status == "waiting_approval"
            stored_input = json.loads(run.input_vars_json or "{}")
            assert stored_input.get("__approval_decisions") in (None, {})
            assert events.scalars().first() is None