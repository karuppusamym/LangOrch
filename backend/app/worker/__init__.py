"""Durable worker package.

The worker processes jobs from the ``run_jobs`` table.

Single-process (SQLite dev):
    Worker runs as an asyncio.Task inside the API process.
    Enabled automatically when WORKER_EMBEDDED=true (default for SQLite).

Multi-process (PostgreSQL production):
    Start the worker separately:
        python -m app.worker          # default worker ID from hostname
        WORKER_ID=w1 python -m app.worker

The worker uses:
- Optimistic locking for SQLite (single event loop — no race conditions).
- SELECT … FOR UPDATE SKIP LOCKED for PostgreSQL (proper distributed locking).
"""
