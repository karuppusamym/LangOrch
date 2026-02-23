"""Approvals API router."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db.engine import async_session, get_db
from app.schemas.approvals import ApprovalDecision, ApprovalOut
from app.services import approval_service, run_service
from app.worker.enqueue import requeue_run
from app.auth import require_role
from app.auth.deps import Principal

router = APIRouter()


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(status: str | None = None, db: AsyncSession = Depends(get_db)):
    return await approval_service.list_approvals(db, status)


@router.get("/stream")
async def stream_approvals(request: Request):
    """SSE endpoint — polls DB for approval changes and streams them."""

    async def event_generator():
        last_snapshot: dict[str, str] = {}
        while True:
            if await request.is_disconnected():
                break
            async with (await _get_approval_session()) as db:
                approvals = await approval_service.list_approvals(db, None)
                current_snapshot: dict[str, str] = {}
                for a in approvals:
                    aid = str(a.approval_id)
                    current_snapshot[aid] = a.status
                    if aid not in last_snapshot or last_snapshot[aid] != a.status:
                        yield {
                            "event": "approval_update",
                            "id": aid,
                            "data": json.dumps({
                                "approval_id": aid,
                                "run_id": str(a.run_id),
                                "node_id": a.node_id,
                                "prompt": a.prompt,
                                "status": a.status,
                                "decided_by": a.decided_by,
                                "decided_at": a.decided_at.isoformat() if a.decided_at else None,
                                "expires_at": a.expires_at.isoformat() if a.expires_at else None,
                                "created_at": a.created_at.isoformat() if a.created_at else None,
                            }),
                        }
                last_snapshot = current_snapshot
            await asyncio.sleep(2)

    return EventSourceResponse(event_generator())


@router.get("/{approval_id}", response_model=ApprovalOut)
async def get_approval(approval_id: str, db: AsyncSession = Depends(get_db)):
    approval = await approval_service.get_approval(db, approval_id)
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found")
    return approval


@router.post("/{approval_id}/decision", response_model=ApprovalOut)
async def submit_decision(
    approval_id: str,
    body: ApprovalDecision,
    db: AsyncSession = Depends(get_db),
    principal: Principal = Depends(require_role("approver")),
):
    # Use authenticated principal as fallback decided_by
    decided_by = body.decided_by or principal.identity
    approval = await approval_service.submit_decision(
        db, approval_id, body.resolved_decision, decided_by, body.payload
    )
    if not approval:
        raise HTTPException(status_code=404, detail="Approval not found or already decided")

    run = await run_service.get_run(db, approval.run_id)
    if run:
        current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
        decisions = current_input.get("__approval_decisions", {})
        if not isinstance(decisions, dict):
            decisions = {}
        decisions[approval.node_id] = approval.status
        current_input["__approval_decisions"] = decisions
        run.input_vars_json = json.dumps(current_input)

        await run_service.update_run_status(db, run.run_id, "created")
        await run_service.emit_event(
            db,
            run.run_id,
            "approval_decision_received",
            node_id=approval.node_id,
            payload={"approval_id": approval.approval_id, "decision": approval.status},
        )

        # Requeue the run so the worker resumes it promptly (priority=10).
        # Uses UPDATE on the existing RunJob row to avoid the unique-constraint
        # violation that would occur if we tried to INSERT a second row for
        # the same run_id.  get_db commits on exit — atomic with the decision.
        await requeue_run(db, run.run_id, priority=10)

    return approval


async def _get_approval_session():
    return async_session()
