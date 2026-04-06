from __future__ import annotations

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app.db.engine import async_session
from app.db.models import Approval, Run
from app.services import procedure_service, run_service
from app.services.execution_service import execute_run
from app.worker.enqueue import enqueue_run, requeue_run


FRAUD_DEMO_CKP_PATH = (
    Path(__file__).resolve().parents[2]
    / "ckp_file-main"
    / "fraud_detection_investigation.ckp copy.json"
)


def _load_fraud_demo_ckp() -> dict:
    return json.loads(FRAUD_DEMO_CKP_PATH.read_text(encoding="utf-8"))


def _base_input_vars(risk_score: int) -> dict:
    return {
        "transaction_id": f"txn-{risk_score}",
        "account_id": f"acct-{risk_score}",
        "transaction_amount": 249.99,
        "transaction_currency": "USD",
        "merchant_id": "merchant-123",
        "channel": "online",
        "risk_score": risk_score,
        "customer_name": "Test Customer",
        "flag": "SUSPICIOUS_ACTIVITY",
    }


async def _setup_fraud_demo_run(input_vars: dict) -> str:
    ckp = _load_fraud_demo_ckp()

    async with async_session() as db:
        existing = await procedure_service.get_procedure(db, ckp["procedure_id"], ckp["version"])
        if existing is None:
            await procedure_service.import_procedure(db, ckp)
        await db.commit()

    async with async_session() as db:
        run = await run_service.create_run(
            db,
            procedure_id=ckp["procedure_id"],
            procedure_version=ckp["version"],
            input_vars=input_vars,
        )
        enqueue_run(db, run.run_id)
        await db.commit()
        return run.run_id


@pytest.mark.asyncio
async def test_fraud_demo_low_risk_job_completes():
    run_id = await _setup_fraud_demo_run(_base_input_vars(risk_score=20))

    await execute_run(run_id, async_session)

    async with async_session() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"

        approvals = (
            await db.execute(select(Approval).where(Approval.run_id == run_id))
        ).scalars().all()
        assert approvals == []


@pytest.mark.asyncio
async def test_fraud_demo_medium_risk_job_waits_for_review_and_resumes():
    run_id = await _setup_fraud_demo_run(_base_input_vars(risk_score=65))

    await execute_run(run_id, async_session)

    async with async_session() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        assert run.status == "waiting_approval"
        assert run.last_node_id == "human_approval_review"

        approval = (
            await db.execute(select(Approval).where(Approval.run_id == run_id))
        ).scalar_one()
        assert approval.status == "pending"
        assert approval.node_id == "human_approval_review"

        current_input = json.loads(run.input_vars_json) if run.input_vars_json else {}
        current_input.setdefault("__approval_decisions", {})[approval.node_id] = "challenge"
        run.input_vars_json = json.dumps(current_input)
        approval.status = "challenge"
        approval.decided_by = "fraud_test"
        await run_service.update_run_status(db, run_id, "created")
        await requeue_run(db, run_id, priority=10)
        await db.commit()

    await execute_run(run_id, async_session)

    async with async_session() as db:
        run = await db.get(Run, run_id)
        assert run is not None
        assert run.status == "completed"

        approval = (
            await db.execute(select(Approval).where(Approval.run_id == run_id))
        ).scalar_one()
        assert approval.status == "challenge"
