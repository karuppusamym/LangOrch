"""Batch 26 tests — SQLite/PostgreSQL dual-dialect support + Alembic migrations + RunJob model.

Tests in this module verify:
1. Settings auto-detection: dialect is derived from the DB URL
2. sync_db_url() returns a synchronous URL for Alembic CLI
3. PostgreSQL URL auto-build from ORCH_DB_* parts
4. engine.py builds correct kwargs for each dialect
5. RunJob ORM model: create/read/update via in-memory SQLite
6. cancellation_requested column added to runs table
7. Alembic migration file (v001) is syntactically correct and well-formed
8. models.py round-trip: all tables created cleanly in in-memory SQLite
"""

from __future__ import annotations

import ast
import pathlib
import pytest
import pytest_asyncio
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy import text


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

_SQLITE_URL = "sqlite+aiosqlite:///:memory:"


async def _make_db() -> tuple:
    """Create an in-memory SQLite engine with all tables and return (engine, session_factory)."""
    from app.db.models import Base

    eng = create_async_engine(_SQLITE_URL, echo=False, future=True)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)
    return eng, factory


# ─────────────────────────────────────────────────────────────────────────────
# 1. Settings — dialect auto-detection
# ─────────────────────────────────────────────────────────────────────────────


class TestSettingsDialectDetection:
    """Settings.ORCH_DB_DIALECT is always derived from the URL scheme."""

    def test_sqlite_url_sets_sqlite_dialect(self):
        from app.config import Settings

        s = Settings(ORCH_DB_URL="sqlite+aiosqlite:///./test.db")
        assert s.ORCH_DB_DIALECT == "sqlite"
        assert s.is_sqlite is True
        assert s.is_postgres is False

    def test_postgresql_asyncpg_url_sets_postgres_dialect(self):
        from app.config import Settings

        s = Settings(ORCH_DB_URL="postgresql+asyncpg://user:pass@localhost:5432/langorch")
        assert s.ORCH_DB_DIALECT == "postgres"
        assert s.is_postgres is True
        assert s.is_sqlite is False

    def test_postgres_short_scheme_sets_postgres_dialect(self):
        from app.config import Settings

        s = Settings(ORCH_DB_URL="postgresql://user:pass@localhost/db")
        assert s.ORCH_DB_DIALECT == "postgres"
        assert s.is_postgres is True

    def test_explicit_dialect_override_is_still_corrected_by_url(self):
        """When the URL clearly has sqlite, dialect must become sqlite even if overridden."""
        from app.config import Settings

        # URL clearly sqlite — validator should normalise
        s = Settings(
            ORCH_DB_URL="sqlite+aiosqlite:///./dev.db",
            ORCH_DB_DIALECT="postgres",  # user mistake
        )
        assert s.ORCH_DB_DIALECT == "sqlite"

    def test_checkpointer_url_auto_set_for_postgres(self):
        """CHECKPOINTER_URL is auto-pointed to the main DB when dialect=postgres."""
        from app.config import Settings

        pg_url = "postgresql+asyncpg://u:p@localhost:5432/langorch"
        s = Settings(ORCH_DB_URL=pg_url)
        assert s.CHECKPOINTER_URL == pg_url

    def test_checkpointer_url_unchanged_for_sqlite(self):
        from app.config import Settings

        s = Settings(ORCH_DB_URL="sqlite+aiosqlite:///./test.db")
        assert s.CHECKPOINTER_URL == "langgraph_checkpoints.sqlite"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Settings.sync_db_url()
# ─────────────────────────────────────────────────────────────────────────────


class TestSyncDbUrl:
    """sync_db_url() strips async drivers so Alembic (sync) can use the URL."""

    def test_aiosqlite_stripped(self):
        from app.config import Settings

        s = Settings(ORCH_DB_URL="sqlite+aiosqlite:///./test.db")
        sync_url = s.sync_db_url()
        assert "+aiosqlite" not in sync_url
        assert sync_url.startswith("sqlite:///")

    def test_asyncpg_stripped(self):
        from app.config import Settings

        pg_url = "postgresql+asyncpg://user:pass@localhost:5432/langorch"
        s = Settings(ORCH_DB_URL=pg_url)
        sync_url = s.sync_db_url()
        assert "+asyncpg" not in sync_url
        assert sync_url.startswith("postgresql://")

    def test_plain_url_unchanged(self):
        from app.config import Settings

        plain = "sqlite:///./test.db"
        s = Settings(ORCH_DB_URL=plain)
        assert s.sync_db_url() == plain


# ─────────────────────────────────────────────────────────────────────────────
# 3. PostgreSQL URL auto-build from parts
# ─────────────────────────────────────────────────────────────────────────────


class TestPostgresUrlAutoBuilder:
    """When dialect=postgres and a password is supplied, URL is built from parts."""

    def test_url_built_from_parts(self):
        from app.config import Settings

        s = Settings(
            ORCH_DB_DIALECT="postgres",
            ORCH_DB_HOST="pg-host",
            ORCH_DB_PORT=5432,
            ORCH_DB_NAME="mydb",
            ORCH_DB_USER="myuser",
            ORCH_DB_PASSWORD="secret",
        )
        assert "postgresql+asyncpg" in s.ORCH_DB_URL
        assert "pg-host" in s.ORCH_DB_URL
        assert "mydb" in s.ORCH_DB_URL
        assert s.is_postgres is True

    def test_url_not_built_without_password(self):
        from app.config import Settings

        # No password → stays at default SQLite URL
        s = Settings(ORCH_DB_DIALECT="postgres")
        # dialect is overridden back to sqlite because URL is still sqlite
        assert s.ORCH_DB_DIALECT == "sqlite"


# ─────────────────────────────────────────────────────────────────────────────
# 4. engine.py — dialect-specific kwargs
# ─────────────────────────────────────────────────────────────────────────────


class TestEngineKwargs:
    """_build_engine_kwargs returns correct kwargs for each dialect."""

    def test_sqlite_kwargs_no_pool_size(self, monkeypatch):
        from app.config import Settings
        import app.db.engine as eng_mod

        monkeypatch.setattr(eng_mod, "settings", Settings(ORCH_DB_URL="sqlite+aiosqlite:///./t.db"))
        kwargs = eng_mod._build_engine_kwargs()
        assert "pool_size" not in kwargs
        assert "connect_args" in kwargs

    def test_postgres_kwargs_has_pool_size(self, monkeypatch):
        from app.config import Settings
        import app.db.engine as eng_mod

        monkeypatch.setattr(
            eng_mod,
            "settings",
            Settings(ORCH_DB_URL="postgresql+asyncpg://u:p@h:5432/db"),
        )
        kwargs = eng_mod._build_engine_kwargs()
        assert "pool_size" in kwargs
        assert kwargs["pool_pre_ping"] is True
        assert "connect_args" not in kwargs

    def test_alembic_kwargs_sqlite_no_null_pool(self, monkeypatch):
        from app.config import Settings
        import app.db.engine as eng_mod

        monkeypatch.setattr(eng_mod, "settings", Settings(ORCH_DB_URL="sqlite+aiosqlite:///./t.db"))
        kwargs = eng_mod._build_alembic_engine_kwargs()
        assert "NullPool" not in str(kwargs)

    def test_alembic_kwargs_postgres_has_null_pool(self, monkeypatch):
        from app.config import Settings
        import app.db.engine as eng_mod
        from sqlalchemy.pool import NullPool

        monkeypatch.setattr(
            eng_mod,
            "settings",
            Settings(ORCH_DB_URL="postgresql+asyncpg://u:p@h:5432/db"),
        )
        kwargs = eng_mod._build_alembic_engine_kwargs()
        assert kwargs.get("poolclass") is NullPool


# ─────────────────────────────────────────────────────────────────────────────
# 5. RunJob model — CRUD via in-memory SQLite
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_job_create_and_read():
    """RunJob can be created, read, and updated in a SQLite :memory: DB."""
    from app.db.models import Run, RunJob

    eng, factory = await _make_db()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        # First create a parent Run (FK constraint)
        run = Run(
            procedure_id="test_proc",
            procedure_version="1.0",
            thread_id="t1",
            status="created",
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.flush()  # get run_id

        job = RunJob(
            run_id=run.run_id,
            status="queued",
            priority=0,
            available_at=now,
            created_at=now,
            updated_at=now,
        )
        db.add(job)
        await db.commit()

    async with factory() as db:
        from sqlalchemy import select

        result = await db.execute(select(RunJob).where(RunJob.run_id == run.run_id))
        fetched = result.scalar_one()
        assert fetched.status == "queued"
        assert fetched.attempts == 0
        assert fetched.max_attempts == 3
        assert fetched.locked_by is None

    await eng.dispose()


@pytest.mark.asyncio
async def test_run_job_status_transitions():
    """RunJob status can be updated from queued → running → done."""
    from app.db.models import Run, RunJob
    from sqlalchemy import select, update

    eng, factory = await _make_db()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        run = Run(
            procedure_id="p1", procedure_version="1.0", thread_id="t2",
            status="created", created_at=now, updated_at=now,
        )
        db.add(run)
        await db.flush()
        job = RunJob(
            run_id=run.run_id, status="queued", available_at=now,
            created_at=now, updated_at=now,
        )
        db.add(job)
        await db.commit()
        job_id = job.job_id

    # Claim
    async with factory() as db:
        await db.execute(
            update(RunJob)
            .where(RunJob.job_id == job_id)
            .values(status="running", locked_by="worker-1", attempts=1)
        )
        await db.commit()

    # Complete
    async with factory() as db:
        await db.execute(
            update(RunJob)
            .where(RunJob.job_id == job_id)
            .values(status="done", locked_by=None)
        )
        await db.commit()

    async with factory() as db:
        result = await db.execute(select(RunJob).where(RunJob.job_id == job_id))
        job = result.scalar_one()
        assert job.status == "done"
        assert job.locked_by is None

    await eng.dispose()


@pytest.mark.asyncio
async def test_run_job_poll_index_columns_exist():
    """The run_jobs table must expose status, available_at, priority for the poll index."""
    from app.db.models import RunJob

    columns = {c.key for c in RunJob.__table__.columns}
    assert "status" in columns
    assert "available_at" in columns
    assert "priority" in columns
    assert "locked_by" in columns
    assert "locked_until" in columns
    assert "attempts" in columns
    assert "max_attempts" in columns


# ─────────────────────────────────────────────────────────────────────────────
# 6. cancellation_requested on Run
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cancellation_requested_column_default_false():
    """cancellation_requested defaults to False on new Run rows."""
    from app.db.models import Run
    from sqlalchemy import select

    eng, factory = await _make_db()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        run = Run(
            procedure_id="p_cancel",
            procedure_version="1.0",
            thread_id="tc1",
            status="running",
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.commit()
        run_id = run.run_id

    async with factory() as db:
        result = await db.execute(select(Run).where(Run.run_id == run_id))
        r = result.scalar_one()
        assert r.cancellation_requested is False

    await eng.dispose()


@pytest.mark.asyncio
async def test_cancellation_requested_can_be_set():
    """cancellation_requested can be flipped to True (DB-level cancel signal)."""
    from app.db.models import Run
    from sqlalchemy import select, update

    eng, factory = await _make_db()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        run = Run(
            procedure_id="p_cancel2",
            procedure_version="1.0",
            thread_id="tc2",
            status="running",
            created_at=now,
            updated_at=now,
        )
        db.add(run)
        await db.commit()
        run_id = run.run_id

    async with factory() as db:
        await db.execute(
            update(Run)
            .where(Run.run_id == run_id)
            .values(cancellation_requested=True)
        )
        await db.commit()

    async with factory() as db:
        result = await db.execute(select(Run).where(Run.run_id == run_id))
        r = result.scalar_one()
        assert r.cancellation_requested is True

    await eng.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 7. Alembic migration file is well-formed
# ─────────────────────────────────────────────────────────────────────────────

_MIGRATION_FILE = (
    pathlib.Path(__file__).parents[1] / "alembic" / "versions" / "v001_initial_schema.py"
)


class TestAlembicMigration:
    """Alembic migration v001 exists and has the required structure — checked via AST."""

    def test_migration_file_exists(self):
        assert _MIGRATION_FILE.exists(), f"Migration file not found: {_MIGRATION_FILE}"

    def test_migration_parses_as_valid_python(self):
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        tree = ast.parse(src)  # raises SyntaxError if invalid
        assert tree is not None

    def test_migration_has_correct_revision(self):
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        assert 'revision: str = "v001"' in src or "revision = \"v001\"" in src

    def test_migration_down_revision_is_none(self):
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        assert "down_revision" in src
        assert "None" in src  # down_revision must be None for the initial migration

    def test_migration_has_upgrade_function(self):
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "upgrade" in fn_names

    def test_migration_has_downgrade_function(self):
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        tree = ast.parse(src)
        fn_names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "downgrade" in fn_names

    def test_migration_upgrade_creates_all_tables(self):
        """upgrade() source refers to all expected table names."""
        src = _MIGRATION_FILE.read_text(encoding="utf-8")
        expected_tables = [
            "projects",
            "procedures",
            "runs",
            "run_events",
            "approvals",
            "step_idempotency",
            "artifacts",
            "agent_instances",
            "resource_leases",
            "trigger_registrations",
            "trigger_dedupe_records",
            "run_jobs",
        ]
        for table in expected_tables:
            assert table in src, f"Migration upgrade() missing table: {table}"


# ─────────────────────────────────────────────────────────────────────────────
# 8. All tables created cleanly in in-memory SQLite
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_all_tables_created_in_memory():
    """Base.metadata.create_all creates every expected table in SQLite."""
    from app.db.models import Base

    expected = {
        "projects",
        "procedures",
        "runs",
        "run_events",
        "approvals",
        "step_idempotency",
        "artifacts",
        "agent_instances",
        "resource_leases",
        "trigger_registrations",
        "trigger_dedupe_records",
        "run_jobs",
    }

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with eng.connect() as conn:
        result = await conn.execute(
            text("SELECT name FROM sqlite_master WHERE type='table'")
        )
        actual = {row[0] for row in result.fetchall()}

    await eng.dispose()

    missing = expected - actual
    assert not missing, f"Tables missing from schema: {missing}"


@pytest.mark.asyncio
async def test_run_jobs_poll_index_created():
    """ix_run_jobs_poll index exists in SQLite."""
    from app.db.models import Base

    eng = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with eng.connect() as conn:
        result = await conn.execute(text("SELECT name FROM sqlite_master WHERE type='index'"))
        indexes = {row[0] for row in result.fetchall()}

    await eng.dispose()
    assert "ix_run_jobs_poll" in indexes


# ─────────────────────────────────────────────────────────────────────────────
# 9. RunJob unique constraint — one job per run
# ─────────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_job_unique_per_run():
    """A second RunJob for the same run_id violates the unique constraint."""
    from app.db.models import Run, RunJob
    from sqlalchemy.exc import IntegrityError

    eng, factory = await _make_db()
    now = datetime.now(timezone.utc)

    async with factory() as db:
        run = Run(
            procedure_id="p_uniq", procedure_version="1.0", thread_id="tu1",
            status="created", created_at=now, updated_at=now,
        )
        db.add(run)
        await db.flush()
        job1 = RunJob(run_id=run.run_id, status="queued", available_at=now,
                      created_at=now, updated_at=now)
        db.add(job1)
        await db.commit()
        run_id = run.run_id

    with pytest.raises(IntegrityError):
        async with factory() as db:
            job2 = RunJob(run_id=run_id, status="queued", available_at=now,
                          created_at=now, updated_at=now)
            db.add(job2)
            await db.commit()

    await eng.dispose()


# ─────────────────────────────────────────────────────────────────────────────
# 10. models.py imports cleanly and all expected classes are present
# ─────────────────────────────────────────────────────────────────────────────


class TestModelsModule:
    def test_all_model_classes_importable(self):
        from app.db import models

        expected_classes = [
            "Project",
            "Procedure",
            "Run",
            "RunEvent",
            "Approval",
            "StepIdempotency",
            "Artifact",
            "AgentInstance",
            "ResourceLease",
            "TriggerRegistration",
            "TriggerDedupeRecord",
            "RunJob",
        ]
        for cls_name in expected_classes:
            assert hasattr(models, cls_name), f"models.py missing class: {cls_name}"

    def test_run_has_cancellation_requested(self):
        from app.db.models import Run

        col_names = {c.key for c in Run.__table__.columns}
        assert "cancellation_requested" in col_names

    def test_run_job_fk_to_runs(self):
        from app.db.models import RunJob

        fk_targets = {
            fk.target_fullname for fk in RunJob.__table__.foreign_keys
        }
        assert "runs.run_id" in fk_targets
