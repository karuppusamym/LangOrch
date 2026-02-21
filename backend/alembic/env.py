"""Alembic migration environment — supports both SQLite (dev) and PostgreSQL (prod).

Run migrations:
    # From the backend/ directory:
    alembic upgrade head          # apply all pending migrations
    alembic revision --autogenerate -m "describe change"   # generate new migration
    alembic downgrade -1          # roll back one revision

Environment variables (same as the app):
    ORCH_DB_URL      Override the target database URL
    ORCH_DB_DIALECT  auto-detected from URL; set explicitly only if needed

The env.py uses the *synchronous* URL from settings.sync_db_url() because
Alembic's built-in context.run_migrations() is synchronous.  The async engine
is used at runtime by the FastAPI app but not for migrations.
"""

from __future__ import annotations

import sys
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# ── Make sure the backend package is importable from `alembic/` ────────────
# When running `alembic` from the backend/ directory this isn't needed, but
# it ensures the import works from any cwd.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.config import settings          # noqa: E402  (after sys.path tweak)
from app.db.models import Base           # noqa: E402  (imports all ORM models)

# ── Alembic Config ──────────────────────────────────────────────────────────
config = context.config

# Set up logging from alembic.ini [loggers] section if present
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Target metadata for --autogenerate
target_metadata = Base.metadata

# Override the URL from app settings (supports .env files automatically)
config.set_main_option("sqlalchemy.url", settings.sync_db_url())


# ── Helpers ─────────────────────────────────────────────────────────────────

def run_migrations_offline() -> None:
    """Generate SQL script without connecting to the DB.

    Useful for producing SQL to review / apply manually in production.
    Usage:  alembic upgrade head --sql
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
        render_as_batch=True,  # needed for SQLite ALTER TABLE support
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live DB connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # do not pool connections during migration
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
            compare_server_default=True,
            # render_as_batch=True enables ALTER TABLE support in SQLite
            # (SQLite cannot ALTER tables natively, so Alembic rewrites them)
            render_as_batch=settings.is_sqlite,
        )
        with context.begin_transaction():
            context.run_migrations()


# ── Entry point ─────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
