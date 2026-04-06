from __future__ import annotations

import json

import pytest

from app.db.engine import async_session
from app.db.models import BatchJob, Run, RunEvent
from app.services import case_procedure_policy_service, case_service, data_hardening_service, run_service


@pytest.mark.asyncio
async def test_scrub_historical_run_data_dry_run_and_apply():
    async with async_session() as db:
        case_row = await case_service.create_case(db, title="Legacy case", case_type="legacy")
        run = await run_service.create_run(
            db,
            procedure_id="legacy-proc",
            procedure_version="1.0.0",
            input_vars={
                "customer_id": "123",
                "admin_password": "super-secret",
                "env": {"TOKEN": "abc"},
            },
            case_id=case_row.case_id,
        )
        run.output_vars_json = json.dumps(
            {
                "result": "ok",
                "admin_password": "top-secret",
                "env": {"DB_PASSWORD": "pw"},
            }
        )
        db.add(
            RunEvent(
                run_id=run.run_id,
                event_type="run_completed",
                payload_json=json.dumps(
                    {
                        "outputs": {
                            "result": "ok",
                            "admin_password": "top-secret",
                            "env": {"DB_PASSWORD": "pw"},
                        }
                    }
                ),
            )
        )
        await db.commit()

        dry_run = await data_hardening_service.scrub_historical_run_data(db, dry_run=True)
        assert dry_run["run_rows_updated"] == 1
        assert dry_run["event_rows_updated"] == 1

        same_run = await run_service.get_run(db, run.run_id)
        assert same_run is not None
        assert "admin_password" in json.loads(same_run.output_vars_json or "{}")

        applied = await data_hardening_service.scrub_historical_run_data(db, dry_run=False)
        await db.commit()
        assert applied["run_rows_updated"] == 1
        assert applied["event_rows_updated"] == 1

        refreshed_run = await run_service.get_run(db, run.run_id)
        assert refreshed_run is not None
        scrubbed_output = json.loads(refreshed_run.output_vars_json or "{}")
        assert scrubbed_output["result"] == "ok"
        assert scrubbed_output["admin_password"] == "***REDACTED***"
        assert "env" not in scrubbed_output

        event_rows = await run_service.list_events(db, run.run_id)
        completed_event = next(event for event in event_rows if event.event_type == "run_completed")
        payload = json.loads(completed_event.payload_json or "{}")
        assert payload["outputs"]["admin_password"] == "***REDACTED***"
        assert "env" not in payload["outputs"]


@pytest.mark.asyncio
async def test_backfill_case_types_and_seed_policies():
    async with async_session() as db:
        explicit_case = await case_service.create_case(
            db,
            title="Batch-inferred case",
            case_type=None,
        )
        fallback_case = await case_service.create_case(
            db,
            title="Procedure-inferred case",
            case_type=None,
        )

        batch = BatchJob(
            name="legacy batch",
            procedure_id="finder-proc",
            procedure_version="1.0.0",
            case_type="finder_enrollment",
            total_items=1,
            source_format="json",
            create_case_per_item=True,
            status="completed",
        )
        db.add(batch)
        await db.flush()

        await run_service.create_run(
            db,
            procedure_id="finder-proc",
            procedure_version="1.0.0",
            input_vars={"name": "A"},
            case_id=explicit_case.case_id,
            batch_job_id=batch.batch_job_id,
        )
        await run_service.create_run(
            db,
            procedure_id="legacy-proc",
            procedure_version="1.0.0",
            input_vars={"name": "B"},
            case_id=fallback_case.case_id,
        )
        await db.commit()

        policies_before = await case_procedure_policy_service.list_policies(db)
        report = await data_hardening_service.backfill_case_types_and_seed_policies(db, dry_run=False)
        await db.commit()

        assert report["cases_backfilled"] == 2
        policies_after = await case_procedure_policy_service.list_policies(db)
        assert report["policies_seeded"] >= 2
        assert len(policies_after) - len(policies_before) >= 2

        refreshed_explicit = await case_service.get_case(db, explicit_case.case_id)
        refreshed_fallback = await case_service.get_case(db, fallback_case.case_id)
        assert refreshed_explicit is not None
        assert refreshed_fallback is not None
        assert refreshed_explicit.case_type == "finder_enrollment"
        assert refreshed_fallback.case_type == "legacy__legacy_proc"

        policy_keys = {(row.project_id, row.case_type, row.procedure_id) for row in policies_after}
        assert (None, "finder_enrollment", "finder-proc") in policy_keys
        assert (None, "legacy__legacy_proc", "legacy-proc") in policy_keys
