"""Application settings — loaded from environment variables."""

from __future__ import annotations

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # ── Database ────────────────────────────────────────────────
    # Dialect: sqlite | postgres | sqlserver
    ORCH_DB_DIALECT: str = "sqlite"
    ORCH_DB_URL: str = "sqlite+aiosqlite:///./langorch.db"

    # ── Server ──────────────────────────────────────────────────
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    DEBUG: bool = True

    # ── CORS (frontend) ────────────────────────────────────────
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]

    # ── Checkpointer ───────────────────────────────────────────
    # Uses same DB by default; override for dedicated store
    CHECKPOINTER_URL: str | None = "langgraph_checkpoints.sqlite"

    # ── Lease TTL (seconds) for desktop resource locks ─────────
    LEASE_TTL_SECONDS: int = 300

    # ── Optional MCP fallback ───────────────────────────────────
    MCP_BASE_URL: str | None = None

    # ── LLM connector (OpenAI-compatible endpoint) ─────────────
    LLM_BASE_URL: str = "https://api.openai.com/v1"
    LLM_API_KEY: str | None = None
    LLM_TIMEOUT_SECONDS: float = 60.0

    # ── Alert hooks ─────────────────────────────────────────────
    # When set, a POST is sent to this URL on run_failed events
    ALERT_WEBHOOK_URL: str | None = None

    # ── Rate limiting ───────────────────────────────────────────
    # Default max concurrent runs per procedure (0 = unlimited)
    RATE_LIMIT_MAX_CONCURRENT: int = 0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
