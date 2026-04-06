"""Batch job creation and monitoring service."""

from __future__ import annotations

import csv
import io
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import case as sql_case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BatchJob, BatchJobItem, Run
from app.services import case_procedure_policy_service, case_service, procedure_service, run_service
from app.utils.run_cancel import mark_cancelled as _mark_run_cancelled, mark_cancelled_db as _mark_run_cancelled_db
from app.utils.input_vars import validate_input_vars
from app.worker.enqueue import enqueue_run, requeue_run

RETRYABLE_RUN_STATUSES = {"failed", "canceled", "cancelled"}
CANCELABLE_RUN_STATUSES = {"created", "pending", "running", "waiting_approval"}


def _parse_payload_items(source_format: str, payload_text: str) -> list[dict[str, Any]]:
    if source_format == "json":
        parsed = json.loads(payload_text)
        if isinstance(parsed, list):
            if not all(isinstance(item, dict) for item in parsed):
                raise ValueError("JSON batch payload must be an array of objects")
            return parsed
        if isinstance(parsed, dict) and isinstance(parsed.get("items"), list):
            items = parsed["items"]
            if not all(isinstance(item, dict) for item in items):
                raise ValueError("JSON batch payload items must be objects")
            return items
        raise ValueError("JSON batch payload must be an array or an object with an 'items' array")
    if source_format == "jsonl":
        items: list[dict[str, Any]] = []
        for idx, line in enumerate(payload_text.splitlines(), start=1):
            stripped = line.strip()
            if not stripped:
                continue
            parsed = json.loads(stripped)
            if not isinstance(parsed, dict):
                raise ValueError(f"JSONL row {idx} must be an object")
            items.append(parsed)
        return items
    if source_format == "csv":
        reader = csv.DictReader(io.StringIO(payload_text))
        if not reader.fieldnames:
            raise ValueError("CSV batch payload requires a header row")
        return [dict(row) for row in reader]
    raise ValueError(f"Unsupported batch payload format '{source_format}'")


async def create_batch_job(
    db: AsyncSession,
    *,
    name: str,
    procedure_id: str,
    procedure_version: str,
    payload_text: str,
    source_format: str,
    project_id: str | None,
    create_case_per_item: bool,
    case_type: str | None,
    title_field: str | None,
    external_ref_field: str | None,
    tags: list[str] | None,
    trigger_type: str | None,
    triggered_by: str | None,
) -> BatchJob:
    proc = await procedure_service.get_procedure(db, procedure_id, procedure_version)
    if not proc:
        raise ValueError("Procedure not found")

    items = _parse_payload_items(source_format, payload_text)
    if not items:
        raise ValueError("Batch payload produced no rows")

    schema = {}
    try:
        ckp = json.loads(proc.ckp_json) if proc.ckp_json else {}
        schema = ckp.get("variables_schema") or {}
    except Exception:
        schema = {}

    batch = BatchJob(
        name=name,
        procedure_id=procedure_id,
        procedure_version=procedure_version,
        status="queued",
        source_format=source_format,
        total_items=len(items),
        create_case_per_item=create_case_per_item,
        case_type=case_type,
        trigger_type=trigger_type,
        triggered_by=triggered_by,
        project_id=project_id or proc.project_id,
    )
    db.add(batch)
    await db.flush()
    await db.refresh(batch)

    for idx, item in enumerate(items):
        if schema:
            errors = validate_input_vars(schema, item)
            if errors:
                raise ValueError(f"Invalid input_vars at batch row {idx}: {errors}")

        case_row = None
        if create_case_per_item:
            title = str(item.get(title_field or "title") or f"{name} #{idx + 1}")
            external_ref = None
            if external_ref_field:
                raw_ref = item.get(external_ref_field)
                external_ref = str(raw_ref) if raw_ref not in (None, "") else None
            case_row = await case_service.create_case(
                db,
                title=title,
                project_id=project_id or proc.project_id,
                external_ref=external_ref,
                case_type=case_type,
                status="open",
                priority="normal",
                tags=tags,
                metadata=item,
                require_case_type=True,
            )
            await case_procedure_policy_service.assert_case_allows_procedure(db, case_row, procedure_id)

        run = await run_service.create_run(
            db,
            procedure_id=procedure_id,
            procedure_version=procedure_version,
            input_vars=item,
            project_id=project_id or proc.project_id,
            case_id=case_row.case_id if case_row else None,
            trigger_type=trigger_type,
            triggered_by=triggered_by,
            batch_job_id=batch.batch_job_id,
            batch_item_index=idx,
            link_source="created_from_batch" if case_row is None else "created_from_batch_case",
            input_snapshot_source="batch_row",
        )
        enqueue_run(db, run.run_id)
        batch_item = BatchJobItem(
            batch_job_id=batch.batch_job_id,
            item_index=idx,
            status="queued",
            input_vars_json=json.dumps(item),
            run_id=run.run_id,
            case_id=case_row.case_id if case_row else None,
        )
        db.add(batch_item)

    await db.flush()
    return await get_batch_job(db, batch.batch_job_id) or batch


async def _attach_batch_counts(db: AsyncSession, rows: list[BatchJob]) -> list[BatchJob]:
    if not rows:
        return rows
    batch_ids = [row.batch_job_id for row in rows]
    stmt = (
        select(
            Run.batch_job_id,
            func.sum(sql_case((Run.status.in_(["created", "pending"]), 1), else_=0)).label("queued_items"),
            func.sum(sql_case((Run.status.in_(["running", "waiting_approval"]), 1), else_=0)).label("running_items"),
            func.sum(sql_case((Run.status == "completed", 1), else_=0)).label("completed_items"),
            func.sum(sql_case((Run.status == "failed", 1), else_=0)).label("failed_items"),
            func.sum(sql_case((Run.status.in_(["canceled", "cancelled"]), 1), else_=0)).label("canceled_items"),
        )
        .where(Run.batch_job_id.in_(batch_ids))
        .group_by(Run.batch_job_id)
    )
    counts = {
        row.batch_job_id: row
        for row in (await db.execute(stmt)).all()
    }
    now = datetime.now(timezone.utc)
    for row in rows:
        count_row = counts.get(row.batch_job_id)
        queued = int(getattr(count_row, "queued_items", 0) or 0)
        running = int(getattr(count_row, "running_items", 0) or 0)
        completed = int(getattr(count_row, "completed_items", 0) or 0)
        failed = int(getattr(count_row, "failed_items", 0) or 0)
        canceled = int(getattr(count_row, "canceled_items", 0) or 0)
        row.queued_items = queued  # type: ignore[attr-defined]
        row.running_items = running  # type: ignore[attr-defined]
        row.completed_items = completed  # type: ignore[attr-defined]
        row.failed_items = failed  # type: ignore[attr-defined]
        row.canceled_items = canceled  # type: ignore[attr-defined]
        if running > 0:
            row.status = "running"
            row.completed_at = None
        elif queued > 0:
            row.status = "queued"
            row.completed_at = None
        elif failed > 0 and completed + failed + canceled >= row.total_items:
            row.status = "partial_failed" if completed > 0 or canceled > 0 else "failed"
            row.completed_at = row.completed_at or now
        elif completed >= row.total_items and row.total_items > 0:
            row.status = "completed"
            row.completed_at = row.completed_at or now
        elif canceled > 0 and completed + canceled >= row.total_items:
            row.status = "partial_cancelled" if completed > 0 else "cancelled"
            row.completed_at = row.completed_at or now
        else:
            row.status = "queued"
            row.completed_at = None
    return rows


async def _sync_batch_item_runtime_state(
    db: AsyncSession,
    items: list[BatchJobItem],
) -> list[BatchJobItem]:
    if not items:
        return items

    run_ids = [item.run_id for item in items if item.run_id]
    if not run_ids:
        return items

    runs = {
        row.run_id: row
        for row in (await db.execute(select(Run).where(Run.run_id.in_(run_ids)))).scalars().all()
    }
    changed = False
    for item in items:
        if not item.run_id:
            continue
        run = runs.get(item.run_id)
        if not run:
            continue
        if item.status != run.status:
            item.status = run.status
            changed = True
        run_error = getattr(run, "error_message", None)
        next_error = run_error if run_error else item.error_message
        if item.error_message != next_error:
            item.error_message = next_error
            changed = True
    if changed:
        await db.flush()
    return items


async def list_batch_jobs(
    db: AsyncSession,
    *,
    project_id: str | None = None,
    procedure_id: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[BatchJob]:
    stmt = select(BatchJob).order_by(BatchJob.created_at.desc()).limit(limit).offset(offset)
    if project_id:
        stmt = stmt.where(BatchJob.project_id == project_id)
    if procedure_id:
        stmt = stmt.where(BatchJob.procedure_id == procedure_id)
    rows = list((await db.execute(stmt)).scalars().all())
    return await _attach_batch_counts(db, rows)


async def get_batch_job(db: AsyncSession, batch_job_id: str) -> BatchJob | None:
    row = await db.get(BatchJob, batch_job_id)
    if row is None:
        return None
    rows = await _attach_batch_counts(db, [row])
    return rows[0]


async def list_batch_job_items(db: AsyncSession, batch_job_id: str) -> list[BatchJobItem]:
    stmt = (
        select(BatchJobItem)
        .where(BatchJobItem.batch_job_id == batch_job_id)
        .order_by(BatchJobItem.item_index.asc())
    )
    items = list((await db.execute(stmt)).scalars().all())
    return await _sync_batch_item_runtime_state(db, items)


async def get_batch_job_item(
    db: AsyncSession,
    batch_job_id: str,
    item_id: str,
) -> BatchJobItem | None:
    stmt = (
        select(BatchJobItem)
        .where(BatchJobItem.batch_job_id == batch_job_id, BatchJobItem.item_id == item_id)
        .limit(1)
    )
    item = (await db.execute(stmt)).scalar_one_or_none()
    if item is None:
        return None
    items = await _sync_batch_item_runtime_state(db, [item])
    return items[0]


async def retry_batch_job_item(
    db: AsyncSession,
    batch_job_id: str,
    item_id: str,
) -> BatchJobItem | None:
    item = await get_batch_job_item(db, batch_job_id, item_id)
    if item is None:
        return None
    if not item.run_id:
        raise ValueError("Batch item has no linked run")

    run = await run_service.get_run(db, item.run_id)
    if run is None:
        raise ValueError("Linked run not found")
    if run.status not in RETRYABLE_RUN_STATUSES:
        raise ValueError(f"Run status '{run.status}' is not retryable")

    retried = await run_service.prepare_retry(db, run.run_id)
    if retried is None:
        raise ValueError("Linked run not found")
    await requeue_run(db, retried.run_id)
    item.status = "created"
    item.error_message = None
    await db.flush()
    return item


async def cancel_batch_job_item(
    db: AsyncSession,
    batch_job_id: str,
    item_id: str,
) -> BatchJobItem | None:
    item = await get_batch_job_item(db, batch_job_id, item_id)
    if item is None:
        return None
    if not item.run_id:
        raise ValueError("Batch item has no linked run")

    run = await run_service.get_run(db, item.run_id)
    if run is None:
        raise ValueError("Linked run not found")
    if run.status not in CANCELABLE_RUN_STATUSES:
        raise ValueError(f"Run status '{run.status}' cannot be cancelled")

    await _mark_run_cancelled_db(run.run_id, db)
    _mark_run_cancelled(run.run_id)
    await run_service.cancel_pending_run_job(db, run.run_id)
    cancelled = await run_service.update_run_status(db, run.run_id, "canceled")
    item.status = "canceled"
    item.error_message = getattr(cancelled, "error_message", None)
    await db.flush()
    return item


async def retry_failed_batch_job_items(db: AsyncSession, batch_job_id: str) -> list[BatchJobItem]:
    items = await list_batch_job_items(db, batch_job_id)
    retried: list[BatchJobItem] = []
    for item in items:
        if item.status != "failed":
            continue
        retried_item = await retry_batch_job_item(db, batch_job_id, item.item_id)
        if retried_item is not None:
            retried.append(retried_item)
    return retried


async def cancel_batch_job(db: AsyncSession, batch_job_id: str) -> list[BatchJobItem]:
    items = await list_batch_job_items(db, batch_job_id)
    cancelled: list[BatchJobItem] = []
    for item in items:
        if item.status not in CANCELABLE_RUN_STATUSES:
            continue
        cancelled_item = await cancel_batch_job_item(db, batch_job_id, item.item_id)
        if cancelled_item is not None:
            cancelled.append(cancelled_item)
    return cancelled


async def export_failed_batch_job_items_csv(db: AsyncSession, batch_job_id: str) -> str:
    items = [item for item in await list_batch_job_items(db, batch_job_id) if item.status == "failed"]
    input_keys = sorted(
        {
            key
            for item in items
            for key in (json.loads(item.input_vars_json).keys() if item.input_vars_json else [])
        }
    )
    fieldnames = ["item_index", "item_id", "run_id", "case_id", "status", "error_message", *input_keys]
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        input_vars = json.loads(item.input_vars_json) if item.input_vars_json else {}
        row = {
            "item_index": item.item_index,
            "item_id": item.item_id,
            "run_id": item.run_id,
            "case_id": item.case_id,
            "status": item.status,
            "error_message": item.error_message,
        }
        for key in input_keys:
            row[key] = input_vars.get(key)
        writer.writerow(row)
    return buffer.getvalue()
