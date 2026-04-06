from __future__ import annotations

import pytest

from app.db.engine import async_session
from app.services import batch_job_service, case_procedure_policy_service, case_service, procedure_service, run_service, trigger_service


def _ckp(procedure_id: str, version: str = "1.0.0") -> dict:
    return {
        "procedure_id": procedure_id,
        "version": version,
        "name": procedure_id,
        "global_config": {},
        "variables_schema": {
            "name": {"type": "string", "required": True},
        },
        "workflow_graph": {
            "start_node": "end",
            "nodes": {
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }


@pytest.mark.asyncio
async def test_case_policy_blocks_disallowed_procedure():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("allowed-proc"))
        await procedure_service.import_procedure(db, _ckp("blocked-proc"))
        case_row = await case_service.create_case(
            db,
            title="Policy Case",
            case_type="enrollment",
            metadata={"name": "Example"},
        )
        await case_procedure_policy_service.create_policy(
            db,
            project_id=None,
            case_type="enrollment",
            procedure_id="allowed-proc",
            enabled=True,
        )
        await db.commit()

        await case_procedure_policy_service.assert_case_allows_procedure(db, case_row, "allowed-proc")
        with pytest.raises(ValueError):
            await case_procedure_policy_service.assert_case_allows_procedure(db, case_row, "blocked-proc")


@pytest.mark.asyncio
async def test_batch_job_service_creates_runs_and_cases():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("batch-proc"))
        await case_procedure_policy_service.create_policy(
            db,
            project_id=None,
            case_type="bulk_case",
            procedure_id="batch-proc",
            enabled=True,
        )
        await db.commit()

        job = await batch_job_service.create_batch_job(
            db,
            name="Batch test",
            procedure_id="batch-proc",
            procedure_version="1.0.0",
            payload_text='[{"name":"A","title":"Case A"},{"name":"B","title":"Case B"}]',
            source_format="json",
            project_id=None,
            create_case_per_item=True,
            case_type="bulk_case",
            title_field="title",
            external_ref_field=None,
            tags=["bulk"],
            trigger_type="manual",
            triggered_by="test",
        )
        await db.commit()

        items = await batch_job_service.list_batch_job_items(db, job.batch_job_id)
        assert job.total_items == 2
        assert len(items) == 2
        assert all(item.run_id for item in items)
        assert all(item.case_id for item in items)


@pytest.mark.asyncio
async def test_trigger_service_can_dispatch_batch_and_case_run():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("trigger-proc"))
        await case_procedure_policy_service.create_policy(
            db,
            project_id=None,
            case_type="trigger_case",
            procedure_id="trigger-proc",
            enabled=True,
        )
        await trigger_service.upsert_trigger(
            db,
            "trigger-proc",
            "1.0.0",
            override={
                "trigger_type": "webhook",
                "webhook_secret": "TEST_SECRET",
                "dispatch_mode": "batch",
                "enabled": True,
            },
        )
        batch_result = await trigger_service.fire_trigger(
            db,
            procedure_id="trigger-proc",
            version="1.0.0",
            trigger_type="webhook",
            triggered_by="test",
            input_vars={"items": [{"name": "A"}, {"name": "B"}]},
        )
        assert batch_result["entity_type"] == "batch_job"
        assert batch_result["batch_job_id"]

        await trigger_service.upsert_trigger(
            db,
            "trigger-proc",
            "1.0.0",
            override={
                "trigger_type": "scheduled",
                "schedule": "0 9 * * 1-5",
                "dispatch_mode": "case_run",
                "case_type": "trigger_case",
                "case_title_template": "{name}",
                "enabled": True,
            },
        )
        case_result = await trigger_service.fire_trigger(
            db,
            procedure_id="trigger-proc",
            version="1.0.0",
            trigger_type="scheduled",
            triggered_by="scheduler",
            input_vars={"name": "Created From Trigger"},
        )
        await db.commit()

        assert case_result["entity_type"] == "case_run"
        assert case_result["case_id"]
        assert case_result["run_id"]


@pytest.mark.asyncio
async def test_batch_job_item_retry_cancel_and_export():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("batch-ops-proc"))
        await db.commit()

        job = await batch_job_service.create_batch_job(
            db,
            name="Batch ops",
            procedure_id="batch-ops-proc",
            procedure_version="1.0.0",
            payload_text='[{"name":"A"},{"name":"B"}]',
            source_format="json",
            project_id=None,
            create_case_per_item=False,
            case_type=None,
            title_field=None,
            external_ref_field=None,
            tags=None,
            trigger_type="manual",
            triggered_by="test",
        )
        await db.flush()

        items = await batch_job_service.list_batch_job_items(db, job.batch_job_id)
        assert len(items) == 2

        first_run_id = items[0].run_id
        second_run_id = items[1].run_id
        assert first_run_id and second_run_id

        await run_service.update_run_status(db, first_run_id, "failed", error_message="row failed")
        await run_service.update_run_status(db, second_run_id, "running")

        refreshed = await batch_job_service.list_batch_job_items(db, job.batch_job_id)
        assert refreshed[0].status == "failed"
        assert refreshed[0].error_message == "row failed"
        assert refreshed[1].status == "running"

        retried = await batch_job_service.retry_batch_job_item(db, job.batch_job_id, refreshed[0].item_id)
        assert retried is not None
        assert retried.status == "created"
        assert retried.error_message is None

        cancelled = await batch_job_service.cancel_batch_job_item(db, job.batch_job_id, refreshed[1].item_id)
        assert cancelled is not None
        assert cancelled.status == "canceled"

        await run_service.update_run_status(db, first_run_id, "failed", error_message="export me")
        csv_body = await batch_job_service.export_failed_batch_job_items_csv(db, job.batch_job_id)
        assert "item_index" in csv_body
        assert "export me" in csv_body
        assert "name" in csv_body
        assert "A" in csv_body


@pytest.mark.asyncio
async def test_batch_job_case_creation_requires_case_type():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("batch-case-type-proc"))
        await db.commit()

        with pytest.raises(ValueError, match="case_type is required"):
            await batch_job_service.create_batch_job(
                db,
                name="Missing case type",
                procedure_id="batch-case-type-proc",
                procedure_version="1.0.0",
                payload_text='[{"name":"A","title":"Case A"}]',
                source_format="json",
                project_id=None,
                create_case_per_item=True,
                case_type=None,
                title_field="title",
                external_ref_field=None,
                tags=["bulk"],
                trigger_type="manual",
                triggered_by="test",
            )


@pytest.mark.asyncio
async def test_trigger_case_run_requires_case_type():
    async with async_session() as db:
        await procedure_service.import_procedure(db, _ckp("trigger-missing-case-type"))
        await trigger_service.upsert_trigger(
            db,
            "trigger-missing-case-type",
            "1.0.0",
            override={
                "trigger_type": "scheduled",
                "schedule": "0 9 * * 1-5",
                "dispatch_mode": "case_run",
                "case_title_template": "{name}",
                "enabled": True,
            },
        )

        with pytest.raises(ValueError, match="case_type is required"):
            await trigger_service.fire_trigger(
                db,
                procedure_id="trigger-missing-case-type",
                version="1.0.0",
                trigger_type="scheduled",
                triggered_by="scheduler",
                input_vars={"name": "Created From Trigger"},
            )
