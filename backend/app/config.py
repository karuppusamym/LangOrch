"""Application settings — loaded from environment variables."""

from __future__ import annotations

import os
from pydantic import model_validator
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ────────────────────────────────────────────────
    # Primary DB URL.  Defaults to SQLite (local dev).
    # For PostgreSQL set:
    #   ORCH_DB_URL=postgresql+asyncpg://user:pass@host:5432/langorch
    ORCH_DB_URL: str = "sqlite+aiosqlite:///./langorch.db"

    # Dialect is auto-detected from the URL below — override only if needed.
    ORCH_DB_DIALECT: str = "sqlite"  # sqlite | postgres

    # ── PostgreSQL connection parts (alternative to a full URL) ─
    # If ORCH_DB_URL is not set, these build the connection URL automatically
    # when ORCH_DB_DIALECT=postgres and ORCH_DB_PASSWORD is provided.
    ORCH_DB_HOST: str = "localhost"
    ORCH_DB_PORT: int = 5432
    ORCH_DB_NAME: str = "langorch"
    ORCH_DB_USER: str = "langorch"
    ORCH_DB_PASSWORD: str | None = None

    # PostgreSQL connection pool tunables (ignored for SQLite)
    ORCH_DB_POOL_SIZE: int = 10
    ORCH_DB_MAX_OVERFLOW: int = 20
    ORCH_DB_POOL_TIMEOUT: int = 30

    # ── Server ──────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # ── CORS (frontend) ────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Checkpointer ───────────────────────────────────────────
    # Dev default: SQLite file.
    # For PostgreSQL this is auto-set to ORCH_DB_URL; install
    # langgraph-checkpoint-postgres to enable Postgres checkpointing.
    CHECKPOINTER_URL: str | None = "langgraph_checkpoints.sqlite"

    # ── Lease TTL (seconds) for desktop resource locks ─────────
    LEASE_TTL_SECONDS: int = 300

    # ── Optional MCP fallback ───────────────────────────────────
    MCP_BASE_URL: str | None = None

    # ── LLM connector (OpenAI-compatible endpoint) ─────────────
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str | None = None
    LLM_TIMEOUT_SECONDS: float = 60.0
    LLM_DEFAULT_MODEL: str = "gpt-4o"

    # Extra headers injected on every LLM HTTP call (JSON dict).
    # Useful for API gateway auth, tenant isolation, or quota headers.
    # Example: LLM_GATEWAY_HEADERS='{"X-Tenant-ID": "acme", "X-Quota-Group": "prod"}'
    LLM_GATEWAY_HEADERS: str | None = None

    # JSON override for the per-model cost-per-1k-tokens table.
    # Shape: {"model-name": {"prompt": 0.01, "completion": 0.03}, ...}
    # Merged on top of built-in defaults so you only need to specify overrides.
    LLM_MODEL_COST_JSON: str | None = None

    # ── Apigee Gateway Integration ─────────────────────────────
    APIGEE_ENABLED: bool = False
    APIGEE_TOKEN_URL: str | None = None
    APIGEE_CERTS_PATH: str | None = None
    APIGEE_CONSUMER_KEY: str | None = None
    APIGEE_CLIENT_SECRET: str | None = None
    APIGEE_USE_CASE_ID: str | None = None
    APIGEE_CLIENT_ID: str | None = None

    # ── SSO Integration (Azure AD / OIDC) ──────────────────────
    SSO_ENABLED: bool = False
    SSO_CLIENT_ID: str | None = None
    SSO_CLIENT_SECRET: str | None = None
    SSO_AUTHORITY: str | None = None  # e.g., https://login.microsoftonline.com/your-tenant-id/v2.0
    SSO_REDIRECT_URI: str | None = None  # e.g., http://localhost:8000/api/auth/sso/callback
    
    # JSON dictionary mapping Azure AD Group Object IDs or Roles to LangOrch roles.
    # Format: {"group-uuid-1": "admin", "group-uuid-2": "operator"}
    SSO_ROLE_MAPPING: str | None = None

    # ── Alert hooks ─────────────────────────────────────────────
    # When set, a POST is sent to this URL on run_failed events
    ALERT_WEBHOOK_URL: str | None = None

    # ── Self-referencing base URL ────────────────────────────────
    # Used internally when the Orchestrator needs to build its own callback URL.
    # In production, set this to the load-balanced external URL:
    #   SELF_BASE_URL=https://langorch.mycompany.com
    # In local dev the default below is auto-used.
    SELF_BASE_URL: str = "http://127.0.0.1:8000"

    # ── Rate limiting ───────────────────────────────────────────
    # Default max concurrent runs per procedure (0 = unlimited)
    RATE_LIMIT_MAX_CONCURRENT: int = 0

    # ── Artifacts ───────────────────────────────────────────────
    # Local directory where the orchestrator stores artifact files.
    # Agents may write files here and return a relative URI like
    #   /api/artifacts/<run_id>/<filename>
    # The backend mounts this directory at /api/artifacts (StaticFiles).
    # Override with an absolute path or a cloud bucket mount point.
    ARTIFACTS_DIR: str = "./artifacts"

    # ── Retention ───────────────────────────────────────────────
    # Run events older than this many days will be pruned by the background
    # retention loop (0 = disabled).
    CHECKPOINT_RETENTION_DAYS: int = 30
    # Artifact folders at ARTIFACTS_DIR/<run_id>/ older than this many days
    # will be deleted by the background artifact-retention loop (0 = disabled).
    ARTIFACT_RETENTION_DAYS: int = 30
    # ── Worker (durable job queue) ─────────────────────────────
    # WORKER_EMBEDDED=true  → worker runs as an asyncio.Task inside the API
    #                         process (default for SQLite dev mode).
    # WORKER_EMBEDDED=false → run worker separately with: python -m app.worker
    #                         (required for PostgreSQL multi-process production).
    # When not set explicitly it defaults to True for SQLite and False for PG
    # via the _auto_configure validator.
    WORKER_EMBEDDED: bool | None = None

    # Max concurrent run executions per worker process.
    WORKER_CONCURRENCY: int = 4

    # Seconds between job poll cycles.
    WORKER_POLL_INTERVAL: float = 2.0

    # Seconds a worker holds a job lock before it becomes reclaimable.
    # The heartbeat renews this every WORKER_HEARTBEAT_INTERVAL seconds.
    WORKER_LOCK_DURATION_SECONDS: float = 60.0

    # How often (seconds) the heartbeat task renews the lock.
    WORKER_HEARTBEAT_INTERVAL: float = 15.0

    # Max attempts before a job is marked permanently failed.
    WORKER_MAX_ATTEMPTS: int = 3

    # Delay (seconds) before a failed job becomes eligible for retry.
    # Multiplied by attempt number for linear backoff.
    WORKER_RETRY_DELAY_SECONDS: float = 10.0

    # ── Authentication ───────────────────────────────────────────
    # Set AUTH_ENABLED=true to require JWT Bearer or X-API-Key on all mutating
    # endpoints.  When false (default) every request is treated as an
    # authenticated admin, so all existing tests pass unchanged.
    AUTH_ENABLED: bool = False

    # Secret key used to sign / verify JWT tokens (HS256).
    # MUST be changed in production: AUTH_SECRET_KEY=<random-256-bit-hex>
    AUTH_SECRET_KEY: str = "change-me-in-production-please"

    # JWT token lifetime in minutes.
    AUTH_TOKEN_EXPIRE_MINUTES: int = 60

    # Comma-separated static API keys for machine-to-machine access.
    # Each key grants "operator" role.
    # Example: API_KEYS="key-abc123 key-def456" (space or comma separated)
    API_KEYS: list[str] = []

    # ── Metrics remote export ────────────────────────────────────
    # When set, metrics are pushed to a Prometheus Pushgateway on a background
    # interval using the push API (PUT /metrics/job/<job>).
    METRICS_PUSH_URL: str | None = None

    # How often (seconds) to push metrics to the Pushgateway.
    METRICS_PUSH_INTERVAL_SECONDS: int = 30

    # Job label used in Pushgateway push URL.
    METRICS_PUSH_JOB: str = "langorch"

    # ── Secrets rotation ─────────────────────────────────────────
    # When True, the in-memory secrets cache is invalidated before each run
    # starts, forcing fresh reads from the underlying secrets provider on the
    # first access.  Safe to enable; adds one round-trip per secret per run.
    SECRETS_ROTATION_CHECK: bool = False

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    # ── Computed helpers (not env vars) ────────────────────────

    @model_validator(mode="after")
    def _auto_configure(self) -> "Settings":
        """Auto-detect dialect from URL and build PG URL from parts if needed."""
        url = self.ORCH_DB_URL

        # If user set dialect=postgres with separate parts but no full URL,
        # build the asyncpg URL automatically.
        if (
            url == "sqlite+aiosqlite:///./langorch.db"
            and self.ORCH_DB_DIALECT == "postgres"
            and self.ORCH_DB_PASSWORD is not None
        ):
            composed = (
                f"postgresql+asyncpg://{self.ORCH_DB_USER}:{self.ORCH_DB_PASSWORD}"
                f"@{self.ORCH_DB_HOST}:{self.ORCH_DB_PORT}/{self.ORCH_DB_NAME}"
            )
            object.__setattr__(self, "ORCH_DB_URL", composed)
            url = composed

        # Auto-detect dialect from the URL scheme.
        if url.startswith(("postgresql", "postgres")):
            object.__setattr__(self, "ORCH_DB_DIALECT", "postgres")
        elif url.startswith("sqlite"):
            object.__setattr__(self, "ORCH_DB_DIALECT", "sqlite")

        # For PostgreSQL, auto-point checkpointer at the same DB if still
        # pointing at the SQLite default file.
        if (
            self.ORCH_DB_DIALECT == "postgres"
            and self.CHECKPOINTER_URL == "langgraph_checkpoints.sqlite"
        ):
            object.__setattr__(self, "CHECKPOINTER_URL", self.ORCH_DB_URL)

        # Default WORKER_EMBEDDED: True for SQLite (single-process dev),
        # False for PostgreSQL (worker is a separate process).
        if self.WORKER_EMBEDDED is None:
            object.__setattr__(
                self,
                "WORKER_EMBEDDED",
                self.ORCH_DB_DIALECT == "sqlite",
            )

        return self

    @property
    def is_postgres(self) -> bool:
        return self.ORCH_DB_DIALECT == "postgres"

    @property
    def is_sqlite(self) -> bool:
        return self.ORCH_DB_DIALECT == "sqlite"

    def sync_db_url(self) -> str:
        """Return a *synchronous* DB URL for Alembic CLI / migration tooling.

        asyncpg   → psycopg2  (sync driver; install psycopg2-binary for Alembic CLI)
        aiosqlite → plain sqlite3  (stdlib, always available)
        """
        url = self.ORCH_DB_URL
        if "+asyncpg" in url:
            return url.replace("+asyncpg", "", 1)
        if "+aiosqlite" in url:
            return url.replace("+aiosqlite", "", 1)
        return url


settings = Settings()

# Ensure the artifacts directory exists at import time so StaticFiles can mount it
os.makedirs(settings.ARTIFACTS_DIR, exist_ok=True)
