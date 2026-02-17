"""Events API router — timeline + SSE streaming."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sse_starlette.sse import EventSourceResponse

from app.db.engine import get_db
from app.schemas.events import RunEventOut
from app.services import run_service

router = APIRouter()


@router.get("/runs/{run_id}/events", response_model=list[RunEventOut])
async def list_events(run_id: str, db: AsyncSession = Depends(get_db)):
    return await run_service.list_events(db, run_id)


@router.get("/runs/{run_id}/stream")
async def stream_events(run_id: str, request: Request):
    """SSE endpoint — polls DB for new events and streams them."""

    async def event_generator():
        last_id = 0
        while True:
            if await request.is_disconnected():
                break
            async with (await _get_session()) as db:
                events = await run_service.list_events(db, run_id)
                for ev in events:
                    if ev.event_id > last_id:
                        last_id = ev.event_id
                        payload_data = None
                        if ev.payload_json:
                            try:
                                payload_data = json.loads(ev.payload_json) if isinstance(ev.payload_json, str) else ev.payload_json
                            except Exception:
                                payload_data = None
                        yield {
                            "event": "run_event",
                            "id": str(ev.event_id),
                            "data": json.dumps(
                                {
                                    "event_id": ev.event_id,
                                    "run_id": run_id,
                                    "created_at": ev.ts.isoformat() if ev.ts else None,
                                    "event_type": ev.event_type,
                                    "node_id": ev.node_id,
                                    "step_id": ev.step_id,
                                    "payload": payload_data,
                                }
                            ),
                        }
            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())


async def _get_session():
    from app.db.engine import async_session
    return async_session()
