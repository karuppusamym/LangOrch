"""Maintenance helpers for historical data cleanup and policy backfills."""

from __future__ import annotations

import json
import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import BatchJob, Case, CaseEvent, CaseProcedurePolicy, Run, RunEvent
from app.services import case_procedure_policy_service
from app.utils.redaction import REDACTION_PLACEHOLDER, RUN_CONTEXT_KEYS, sanitize_run_snapshot

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_CASE_TYPE_METADATA_KEYS = ("case_type", "caseType", "workflow_case_type")
_SNAPSHOT_CONTAINER_KEYS = {"input_vars", "inputs", "output_vars", "outputs", "saved_vars", "vars", "variables"}


def _dump_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _load_json(raw: str | None) -> tuple[Any | None, bool]:
    if not raw:
        return None, False
    try:
        return json.loads(raw), True
    except Exception:
        return None, False


def _normalize_case_type_fragment(value: str) -> str:
    normalized = _SLUG_RE.sub("_", value.strip().lower()).strip("_")
    return normalized or "legacy"


def _legacy_case_type_from_procedure(procedure_id: str) -> str:
    return f"legacy__{_normalize_case_type_fragment(procedure_id)}"


def _legacy_case_type_from_case_id(case_id: str) -> str:
    return f"legacy_case__{_normalize_case_type_fragment(case_id[:12])}"


def _scrub_event_payload(data: Any) -> Any:
    if isinstance(data, dict):
        scrubbed: dict[str, Any] = {}
        for key, value in data.items():
            key_str = str(key)
            lowered = key_str.lower()
            if key_str in RUN_CONTEXT_KEYS:
                continue
            if any(token in lowered for token in ("password", "token", "secret", "api_key", "apikey", "authorization", "auth", "credential")):
                scrubbed[key_str] = REDACTION_PLACEHOLDER
                continue
            if key_str in _SNAPSHOT_CONTAINER_KEYS:
                scrubbed[key_str] = sanitize_run_snapshot(value)
                continue
            scrubbed[key_str] = _scrub_event_payload(value)
        return scrubbed
    if isinstance(data, list):
        return [_scrub_event_payload(item) for item in data]
    if isinstance(data, tuple):
        return tuple(_scrub_event_payload(item) for item in data)
    return data


async def scrub_historical_run_data(
    db: AsyncSession,
    *,
    dry_run: bool = True,
) -> dict[str, int]:
    """Redact persisted run snapshots and event payloads written before hardening."""
    report = {
        "runs_scanned": 0,
        "run_rows_updated": 0,
        "run_parse_errors": 0,
        "events_scanned": 0,
        "event_rows_updated": 0,
        "event_parse_errors": 0,
    }

    runs = list((await db.execute(select(Run))).scalars().all())
    for run in runs:
        report["runs_scanned"] += 1
        changed = False
        for attr in ("input_vars_json", "output_vars_json"):
            raw = getattr(run, attr, None)
            if not raw:
                continue
            parsed, ok = _load_json(raw)
            if not ok:
                report["run_parse_errors"] += 1
                continue
            sanitized = sanitize_run_snapshot(parsed)
            serialized = _dump_json(sanitized)
            if serialized != _dump_json(parsed):
                changed = True
                if not dry_run:
                    setattr(run, attr, serialized)
        if changed:
            report["run_rows_updated"] += 1

    events = list((await db.execute(select(RunEvent))).scalars().all())
    for event in events:
        report["events_scanned"] += 1
        if not event.payload_json:
            continue
        parsed, ok = _load_json(event.payload_json)
        if not ok:
            report["event_parse_errors"] += 1
            continue
        scrubbed = _scrub_event_payload(parsed)
        serialized = _dump_json(scrubbed)
        if serialized != _dump_json(parsed):
            report["event_rows_updated"] += 1
            if not dry_run:
                event.payload_json = serialized

    if not dry_run:
        await db.flush()
    return report


async def backfill_case_types_and_seed_policies(
    db: AsyncSession,
    *,
    dry_run: bool = True,
) -> dict[str, int]:
    """Backfill missing ``case_type`` values and seed allow-list policies."""
    report = {
        "cases_scanned": 0,
        "cases_backfilled": 0,
        "policies_seeded": 0,
    }

    cases = list((await db.execute(select(Case).order_by(Case.created_at.asc()))).scalars().all())
    existing_policy_keys = {
        (row.project_id, row.case_type, row.procedure_id)
        for row in (await db.execute(select(CaseProcedurePolicy))).scalars().all()
    }

    for case_row in cases:
        report["cases_scanned"] += 1

        linked_runs = list(
            (
                await db.execute(
                    select(Run).where(Run.case_id == case_row.case_id).order_by(Run.created_at.asc())
                )
            ).scalars().all()
        )

        resolved_case_type = case_row.case_type
        if not resolved_case_type:
            metadata, metadata_ok = _load_json(case_row.metadata_json)
            if metadata_ok and isinstance(metadata, dict):
                for key in _CASE_TYPE_METADATA_KEYS:
                    raw_value = metadata.get(key)
                    if isinstance(raw_value, str) and raw_value.strip():
                        resolved_case_type = raw_value.strip()
                        break

        if not resolved_case_type:
            batch_ids = sorted({run.batch_job_id for run in linked_runs if run.batch_job_id})
            if batch_ids:
                batch_rows = list(
                    (
                        await db.execute(
                            select(BatchJob).where(BatchJob.batch_job_id.in_(batch_ids))
                        )
                    ).scalars().all()
                )
                batch_case_types = sorted(
                    {
                        row.case_type.strip()
                        for row in batch_rows
                        if isinstance(row.case_type, str) and row.case_type.strip()
                    }
                )
                if len(batch_case_types) == 1:
                    resolved_case_type = batch_case_types[0]

        if not resolved_case_type:
            procedure_ids = sorted({run.procedure_id for run in linked_runs if run.procedure_id})
            if len(procedure_ids) == 1:
                resolved_case_type = _legacy_case_type_from_procedure(procedure_ids[0])
            else:
                resolved_case_type = _legacy_case_type_from_case_id(case_row.case_id)

        if case_row.case_type != resolved_case_type:
            report["cases_backfilled"] += 1
            if not dry_run:
                case_row.case_type = resolved_case_type

        for procedure_id in sorted({run.procedure_id for run in linked_runs if run.procedure_id}):
            policy_key = (case_row.project_id, resolved_case_type, procedure_id)
            if policy_key in existing_policy_keys:
                continue
            report["policies_seeded"] += 1
            existing_policy_keys.add(policy_key)
            if not dry_run:
                await case_procedure_policy_service.create_policy(
                    db,
                    project_id=case_row.project_id,
                    case_type=resolved_case_type,
                    procedure_id=procedure_id,
                    enabled=True,
                )

        if not dry_run:
            await db.flush()

    return report

