"""Replay-safe executor wrapper — ensures idempotent external calls."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any, Callable, Awaitable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import StepIdempotency


async def execute_with_idempotency(
    db: AsyncSession,
    run_id: str,
    node_id: str,
    step_id: str,
    executor_fn: Callable[..., Awaitable[Any]],
    *args: Any,
    **kwargs: Any,
) -> Any:
    """
    Check if this step was already successfully executed (replay safety).
    If yes, return the stored result.
    If no, execute and store the result.
    """
    # Check existing
    existing = await db.get(StepIdempotency, (run_id, node_id, step_id))
    if existing and existing.status == "succeeded":
        return json.loads(existing.result_json) if existing.result_json else None

    # Mark as started
    if not existing:
        record = StepIdempotency(
            run_id=run_id,
            node_id=node_id,
            step_id=step_id,
            status="started",
        )
        db.add(record)
        await db.flush()
    else:
        existing.status = "started"
        existing.updated_at = datetime.now(timezone.utc)
        await db.flush()

    try:
        result = await executor_fn(*args, **kwargs)

        # Mark succeeded
        record = await db.get(StepIdempotency, (run_id, node_id, step_id))
        if record:
            record.status = "succeeded"
            record.result_json = json.dumps(result) if result is not None else None
            record.updated_at = datetime.now(timezone.utc)
            await db.flush()

        return result

    except Exception as exc:
        record = await db.get(StepIdempotency, (run_id, node_id, step_id))
        if record:
            record.status = "failed"
            record.result_json = json.dumps({"error": str(exc)})
            record.updated_at = datetime.now(timezone.utc)
            await db.flush()
        raise
