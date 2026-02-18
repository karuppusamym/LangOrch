"""In-memory token-bucket rate limiter.

Each procedure gets its own bucket keyed by `procedure_id`.
Calls to `acquire_rate_limit` block (up to `timeout` seconds) until a token is
available, then consume one token. If the timeout is exceeded the call raises
RuntimeError so the caller can surface a meaningful error instead of hanging.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Callable

logger = logging.getLogger(__name__)

_buckets: dict[str, "_Bucket"] = {}
_creation_lock: asyncio.Lock | None = None  # created lazily (event-loop safe)


def _get_creation_lock() -> asyncio.Lock:
    global _creation_lock
    if _creation_lock is None:
        _creation_lock = asyncio.Lock()
    return _creation_lock


class _Bucket:
    """Thread-safe (asyncio) token bucket."""

    def __init__(self, rate_per_minute: int) -> None:
        self._rate: float = rate_per_minute / 60.0  # tokens per second
        self._capacity: float = float(rate_per_minute)
        self._tokens: float = float(rate_per_minute)
        self._last_refill: float = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, timeout: float = 5.0) -> None:
        """Block until a token is available or *timeout* seconds elapse."""
        deadline = time.monotonic() + timeout
        async with self._lock:
            while True:
                now = time.monotonic()
                elapsed = now - self._last_refill
                self._tokens = min(
                    self._capacity, self._tokens + elapsed * self._rate
                )
                self._last_refill = now

                if self._tokens >= 1.0:
                    self._tokens -= 1.0
                    return

                wait = (1.0 - self._tokens) / self._rate
                if time.monotonic() + wait > deadline:
                    raise RuntimeError(
                        "Rate limit exceeded: max_requests_per_minute reached. "
                        "Retry after a moment or increase "
                        "global_config.rate_limiting.max_requests_per_minute."
                    )
                await asyncio.sleep(min(wait, 0.05))  # check frequently


async def acquire_rate_limit(
    key: str,
    max_per_minute: int,
    timeout: float = 5.0,
) -> None:
    """Acquire a rate-limit token for *key* (normally a procedure_id).

    Creates the bucket on first use. Raises RuntimeError if the rate limit
    cannot be satisfied within *timeout* seconds.
    """
    if key not in _buckets:
        lock = _get_creation_lock()
        async with lock:
            if key not in _buckets:
                logger.info(
                    "Creating token bucket: key=%r max_per_minute=%d",
                    key,
                    max_per_minute,
                )
                _buckets[key] = _Bucket(max_per_minute)

    await _buckets[key].acquire(timeout=timeout)


def reset_bucket(key: str) -> None:
    """Remove the bucket for *key* (useful in tests)."""
    _buckets.pop(key, None)
