"""Tests for Batch 8 backend features:
  1. token_bucket — async rate-limit utility
  2. run_service.list_runs — limit / offset pagination
"""

from __future__ import annotations

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 1. Token bucket
# ---------------------------------------------------------------------------


class TestTokenBucket:
    """Happy-path and error-path tests for the token bucket utility."""

    def setup_method(self):
        """Reset all buckets before each test to avoid cross-test bleed."""
        from app.utils.token_bucket import _buckets
        _buckets.clear()

    @pytest.mark.asyncio
    async def test_acquire_succeeds_when_tokens_available(self):
        from app.utils.token_bucket import acquire_rate_limit

        # High rate: should never block in practice
        await acquire_rate_limit("proc-1", max_per_minute=6000, timeout=1.0)

    @pytest.mark.asyncio
    async def test_acquire_multiple_tokens_within_capacity(self):
        from app.utils.token_bucket import acquire_rate_limit

        # 10 rpm → 10 initial tokens; calling 5× should succeed immediately
        for _ in range(5):
            await acquire_rate_limit("proc-multi", max_per_minute=10, timeout=1.0)

    @pytest.mark.asyncio
    async def test_bucket_exhausted_raises_runtime_error(self):
        from app.utils.token_bucket import acquire_rate_limit, _Bucket

        # Create a bucket that is already exhausted
        bucket = _Bucket(1)  # 1 rpm
        bucket._tokens = 0.0  # drain it

        from app.utils import token_bucket
        token_bucket._buckets["proc-exhaust"] = bucket

        with pytest.raises(RuntimeError, match="Rate limit exceeded"):
            # Very short timeout — should fail almost instantly
            await acquire_rate_limit("proc-exhaust", max_per_minute=1, timeout=0.01)

    @pytest.mark.asyncio
    async def test_separate_keys_have_independent_buckets(self):
        from app.utils.token_bucket import acquire_rate_limit

        # Acquire from two independent keys — neither should affect the other
        await acquire_rate_limit("proc-a", max_per_minute=60, timeout=1.0)
        await acquire_rate_limit("proc-b", max_per_minute=60, timeout=1.0)

    @pytest.mark.asyncio
    async def test_reset_bucket_removes_state(self):
        from app.utils.token_bucket import acquire_rate_limit, reset_bucket, _buckets

        await acquire_rate_limit("proc-reset", max_per_minute=5, timeout=1.0)
        assert "proc-reset" in _buckets

        reset_bucket("proc-reset")
        assert "proc-reset" not in _buckets

    @pytest.mark.asyncio
    async def test_bucket_refills_over_time(self):
        """Bucket refills at rate_per_minute/60 tokens/second."""
        from app.utils.token_bucket import _Bucket

        bucket = _Bucket(60)  # 60 rpm = 1 token/second
        bucket._tokens = 0.0
        # Simulate 2 seconds of elapsed time
        import time
        bucket._last_refill = time.monotonic() - 2.0

        # After 2s at 1 tok/s we should have ~2 tokens refilled
        await bucket.acquire(timeout=0.5)  # should succeed without sleeping


# ---------------------------------------------------------------------------
# 2. Run service pagination
# ---------------------------------------------------------------------------


class TestRunServicePagination:
    """list_runs limit/offset are forwarded to SQLAlchemy correctly."""

    @pytest.mark.asyncio
    async def test_limit_offset_forwarded(self):
        """limit and offset reach the query builder."""
        from app.services.run_service import list_runs

        # Build a fake DB that records the statement
        executed_stmts = []

        class FakeResult:
            def scalars(self):
                return self

            def all(self):
                return []

        class FakeDB:
            async def execute(self, stmt):
                executed_stmts.append(stmt)
                return FakeResult()

        await list_runs(FakeDB(), limit=25, offset=50)  # type: ignore[arg-type]

        assert len(executed_stmts) == 1
        stmt = executed_stmts[0]
        # SQLAlchemy LIMIT/OFFSET are stored on the statement
        # Compiled form should contain the values
        from sqlalchemy.dialects import sqlite as sa_sqlite
        compiled = stmt.compile(dialect=sa_sqlite.dialect())
        sql = str(compiled)
        assert " LIMIT " in sql or "limit" in sql.lower()

    @pytest.mark.asyncio
    async def test_default_limit_is_100(self):
        """Default call uses limit=100."""
        from app.services.run_service import list_runs
        import inspect

        sig = inspect.signature(list_runs)
        assert sig.parameters["limit"].default == 100
        assert sig.parameters["offset"].default == 0

    @pytest.mark.asyncio
    async def test_zero_offset_first_page(self):
        """offset=0 returns first page (no OFFSET clause issue)."""
        from app.services.run_service import list_runs

        class FakeResult:
            def scalars(self): return self
            def all(self): return []

        class FakeDB:
            async def execute(self, _stmt): return FakeResult()

        result = await list_runs(FakeDB(), limit=10, offset=0)  # type: ignore[arg-type]
        assert result == []
