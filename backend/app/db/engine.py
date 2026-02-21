"""SQLAlchemy async engine and session factory."""

from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import settings


def _build_engine_kwargs() -> dict:
    """Return engine kwargs appropriate for the configured dialect."""
    if settings.is_postgres:
        return {
            "echo": settings.DEBUG,
            "future": True,
            "pool_size": settings.ORCH_DB_POOL_SIZE,
            "max_overflow": settings.ORCH_DB_MAX_OVERFLOW,
            "pool_timeout": settings.ORCH_DB_POOL_TIMEOUT,
            "pool_pre_ping": True,   # ensure stale connections are recycled
            "pool_recycle": 1800,    # recycle connections older than 30 min
        }
    # SQLite — single-file, no pool tunables
    return {
        "echo": settings.DEBUG,
        "future": True,
        # aiosqlite is inherently single‑connection; connect_args are ignored
        # but the check_same_thread kwarg avoids the stdlib warning.
        "connect_args": {"check_same_thread": False},
    }


def _build_alembic_engine_kwargs() -> dict:
    """Return engine kwargs for Alembic migrations (NullPool, no echo)."""
    if settings.is_postgres:
        return {"poolclass": NullPool, "future": True}
    return {"future": True, "connect_args": {"check_same_thread": False}}


engine = create_async_engine(settings.ORCH_DB_URL, **_build_engine_kwargs())


if settings.is_sqlite:
    # Enable WAL journal mode for SQLite: allows concurrent reads alongside a
    # single writer, dramatically reducing "database is locked" errors when the
    # embedded worker and health-poll tasks both write at the same time.
    # busy_timeout=5000 makes SQLite wait up to 5 s before raising OperationalError.
    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragmas(dbapi_conn, _conn_rec):  # type: ignore[misc]
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.execute("PRAGMA synchronous=NORMAL")   # safe with WAL, faster than FULL
        cursor.close()


async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_db() -> AsyncSession:  # type: ignore[misc]
    """FastAPI dependency — yields a session and commits/rollbacks."""
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

