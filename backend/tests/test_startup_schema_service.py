from __future__ import annotations

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.services import startup_schema_service


def test_resolve_startup_schema_mode_rejects_postgres_bootstrap(monkeypatch):
    monkeypatch.setattr(startup_schema_service.settings, "ORCH_DB_DIALECT", "postgres")
    monkeypatch.setattr(startup_schema_service.settings, "STARTUP_SCHEMA_MODE", "bootstrap")
    with pytest.raises(ValueError, match="SQLite development databases"):
        startup_schema_service.resolve_startup_schema_mode()


@pytest.mark.asyncio
async def test_assert_database_schema_current_accepts_matching_head(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('v015_batch_jobs_and_case_policies')"))

    monkeypatch.setattr(startup_schema_service, "async_session", session_factory)
    monkeypatch.setattr(
        startup_schema_service,
        "get_expected_alembic_heads",
        lambda: {"v015_batch_jobs_and_case_policies"},
    )

    heads = await startup_schema_service.assert_database_schema_current()
    assert heads == {"v015_batch_jobs_and_case_policies"}

    await engine.dispose()


@pytest.mark.asyncio
async def test_assert_database_schema_current_rejects_outdated_revision(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.execute(text("CREATE TABLE alembic_version (version_num VARCHAR(64) NOT NULL)"))
        await conn.execute(text("INSERT INTO alembic_version (version_num) VALUES ('v014_automation_sessions')"))

    monkeypatch.setattr(startup_schema_service, "async_session", session_factory)
    monkeypatch.setattr(
        startup_schema_service,
        "get_expected_alembic_heads",
        lambda: {"v015_batch_jobs_and_case_policies"},
    )

    with pytest.raises(RuntimeError, match="alembic upgrade head"):
        await startup_schema_service.assert_database_schema_current()

    await engine.dispose()
