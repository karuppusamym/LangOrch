"""Startup-time database schema policy helpers."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.config import settings
from app.db.engine import async_session

_VALID_SCHEMA_MODES = {"auto", "bootstrap", "migrate_check"}


def resolve_startup_schema_mode() -> str:
    raw_mode = (settings.STARTUP_SCHEMA_MODE or "auto").strip().lower()
    if raw_mode not in _VALID_SCHEMA_MODES:
        raise ValueError(
            f"Invalid STARTUP_SCHEMA_MODE '{settings.STARTUP_SCHEMA_MODE}'. "
            f"Expected one of: {', '.join(sorted(_VALID_SCHEMA_MODES))}."
        )
    if raw_mode == "auto":
        return "bootstrap" if settings.is_sqlite else "migrate_check"
    if raw_mode == "bootstrap" and settings.is_postgres:
        raise ValueError(
            "STARTUP_SCHEMA_MODE=bootstrap is only supported for SQLite development databases. "
            "Use Alembic migrations for PostgreSQL environments."
        )
    return raw_mode


def get_expected_alembic_heads() -> set[str]:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    return set(ScriptDirectory.from_config(config).get_heads())


async def assert_database_schema_current() -> set[str]:
    """Fail startup when the connected DB is not at the repo's Alembic head."""
    expected_heads = get_expected_alembic_heads()
    try:
        async with async_session() as db:
            result = await db.execute(text("SELECT version_num FROM alembic_version"))
            applied_heads = {str(row[0]) for row in result.fetchall() if row[0]}
    except SQLAlchemyError as exc:
        raise RuntimeError(
            "Database schema is not ready for startup. "
            "Run `alembic upgrade head` before starting the API."
        ) from exc

    if applied_heads != expected_heads:
        raise RuntimeError(
            "Database schema is behind the application code. "
            f"Expected Alembic head(s): {sorted(expected_heads)}; "
            f"found: {sorted(applied_heads)}. "
            "Run `alembic upgrade head` before starting the API."
        )
    return applied_heads
