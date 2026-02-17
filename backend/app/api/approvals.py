"""Approvals API router."""

from __future__ import annotations

import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.engine import async_session, get_db
from app.schemas.approvals import ApprovalDecision, ApprovalOut
from app.services import approval_service, run_service
from app.services.execution_service import execute_run

router = APIRouter()


@router.get("", response_model=list[ApprovalOut])
async def list_approvals(status: str | None = None, db: AsyncSession = Depends(get_db)):
    return await approval_service.list_approvals(db, status)


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
    background: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
):
    approval = await approval_service.submit_decision(
        db, approval_id, body.resolved_decision, body.decided_by, body.payload
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

        # Ensure decision/update is persisted before resumed worker starts.
        await db.commit()
        background.add_task(execute_run, run.run_id, async_session)

    return approval
