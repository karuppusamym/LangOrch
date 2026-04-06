"""Database automation agent with sqlite, ODBC, and JDBC adapters."""

from __future__ import annotations

import importlib
import os
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest

from automation_agents.shared import AutomationAgentSettings, build_agent_app
from automation_agents.runtime_support import array_schema, build_session_store, object_schema, string_schema


@dataclass
class DatabaseProviderSettings:
    provider: str = os.getenv("DATABASE_AGENT_PROVIDER", "sqlite")


PROVIDER_SETTINGS = DatabaseProviderSettings()

SETTINGS = AutomationAgentSettings(
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("DATABASE_AGENT_ID", "database-automation-agent"),
    agent_name=os.getenv("DATABASE_AGENT_NAME", "Database Automation Agent"),
    agent_port=int(os.getenv("DATABASE_AGENT_PORT", "9011")),
    channel=os.getenv("DATABASE_AGENT_CHANNEL", "database"),
    pool_id=os.getenv("DATABASE_AGENT_POOL_ID", "database_pool"),
    resource_key=os.getenv("DATABASE_AGENT_RESOURCE_KEY", "database_default"),
    concurrency_limit=int(os.getenv("DATABASE_AGENT_CONCURRENCY", "4")),
    description="Database automation with sqlite, ODBC, and JDBC adapters behind one contract.",
)

CAPABILITIES = [
    AgentCapability(
        name="open_session",
        description="Create a reusable database session with connection defaults",
        input_schema=object_schema(
            properties={
                "provider": string_schema(enum=["sqlite", "sqlite3", "odbc", "jdbc"]),
                "database_url": string_schema(),
                "connection_string": string_schema(),
                "jdbc_url": string_schema(),
                "driver_class": string_schema(),
                "username": string_schema(),
                "password": string_schema(),
                "jars": array_schema(string_schema()),
            }
        ),
        output_schema=object_schema(
            required=["session_id", "expires_at", "created_at"],
            properties={"session_id": string_schema()},
        ),
        side_effect_level="none",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="resume_session",
        description="Inspect the active database session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=object_schema(
            required=["session_id", "created_at", "last_used_at", "expires_at", "data"],
            properties={"session_id": string_schema(), "data": object_schema()},
        ),
        side_effect_level="none",
        idempotent=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="close_session",
        description="Close the active database session",
        input_schema=object_schema(required=["session_id"], properties={"session_id": string_schema()}),
        output_schema=object_schema(
            required=["session_id", "closed"],
            properties={"session_id": string_schema(), "closed": {"type": "boolean"}},
        ),
        side_effect_level="low",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="execute_query",
        description="Execute parameterized SQL",
        input_schema=object_schema(
            required=["query"],
            properties={
                "provider": string_schema(enum=["sqlite", "sqlite3", "odbc", "jdbc"]),
                "database_url": string_schema(),
                "connection_string": string_schema(),
                "jdbc_url": string_schema(),
                "driver_class": string_schema(),
                "query": string_schema(),
                "query_params": array_schema({}),
            },
        ),
        output_schema=object_schema(
            required=["provider", "rowcount"],
            properties={"provider": string_schema(), "rows": array_schema(object_schema()), "rowcount": {"type": "integer"}},
        ),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="bulk_insert",
        description="Insert many rows into a table",
        input_schema=object_schema(
            required=["table", "rows"],
            properties={
                "provider": string_schema(enum=["sqlite", "sqlite3", "odbc", "jdbc"]),
                "database_url": string_schema(),
                "connection_string": string_schema(),
                "jdbc_url": string_schema(),
                "driver_class": string_schema(),
                "table": string_schema(),
                "rows": array_schema(object_schema()),
            },
        ),
        output_schema=object_schema(
            required=["provider", "rowcount", "table"],
            properties={"provider": string_schema(), "rowcount": {"type": "integer"}, "table": string_schema()},
        ),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="bulk_update",
        description="Update many rows by key columns",
        input_schema=object_schema(
            required=["table", "rows", "key_columns"],
            properties={
                "provider": string_schema(enum=["sqlite", "sqlite3", "odbc", "jdbc"]),
                "database_url": string_schema(),
                "connection_string": string_schema(),
                "jdbc_url": string_schema(),
                "driver_class": string_schema(),
                "table": string_schema(),
                "rows": array_schema(object_schema()),
                "key_columns": array_schema(string_schema()),
            },
        ),
        output_schema=object_schema(
            required=["provider", "rowcount", "table"],
            properties={"provider": string_schema(), "rowcount": {"type": "integer"}, "table": string_schema()},
        ),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
    AgentCapability(
        name="backup_data",
        description="Copy a SQLite database file",
        input_schema=object_schema(required=["database_url", "output_path"], properties={"database_url": string_schema(), "output_path": string_schema()}),
        output_schema=object_schema(required=["database_url", "output_path", "provider"], properties={"database_url": string_schema(), "output_path": string_schema(), "provider": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
        session_scoped=True,
    ),
    AgentCapability(
        name="restore_data",
        description="Restore a SQLite database file from backup",
        input_schema=object_schema(required=["database_url", "source_path"], properties={"database_url": string_schema(), "source_path": string_schema()}),
        output_schema=object_schema(required=["database_url", "source_path", "provider"], properties={"database_url": string_schema(), "source_path": string_schema(), "provider": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
        session_scoped=True,
    ),
]

SESSION_STORE = build_session_store(agent_id=SETTINGS.agent_id, channel=SETTINGS.channel, timeout_s=SETTINGS.session_timeout_s)


class DatabaseAdapter:
    provider_name = "base"
    placeholder = "?"

    def connect(self, params: dict[str, Any]) -> Any:
        raise NotImplementedError

    def backup(self, params: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(f"{self.provider_name} does not support backup_data")

    def restore(self, params: dict[str, Any]) -> dict[str, Any]:
        raise ValueError(f"{self.provider_name} does not support restore_data")

    def rows(self, cursor: Any) -> list[dict[str, Any]]:
        if not getattr(cursor, "description", None):
            return []
        columns = [column[0] for column in cursor.description]
        output: list[dict[str, Any]] = []
        for row in cursor.fetchall():
            if isinstance(row, dict):
                output.append(row)
            elif hasattr(row, "keys"):
                output.append({key: row[key] for key in row.keys()})
            else:
                output.append(dict(zip(columns, row)))
        return output

    def _execute_query(self, connection: Any, params: dict[str, Any]) -> dict[str, Any]:
        cursor = connection.cursor()
        cursor.execute(params["query"], params.get("query_params") or [])
        if getattr(cursor, "description", None):
            return {"rows": self.rows(cursor), "rowcount": getattr(cursor, "rowcount", -1)}
        connection.commit()
        return {"rowcount": getattr(cursor, "rowcount", -1)}

    def _bulk_insert(self, connection: Any, params: dict[str, Any]) -> dict[str, Any]:
        rows = params.get("rows") or []
        if not rows:
            return {"rowcount": 0, "table": params["table"]}
        columns = list(rows[0].keys())
        placeholders = ", ".join(self.placeholder for _ in columns)
        sql = f"INSERT INTO {params['table']} ({', '.join(columns)}) VALUES ({placeholders})"
        values = [[row.get(column) for column in columns] for row in rows]
        cursor = connection.cursor()
        cursor.executemany(sql, values)
        connection.commit()
        return {"rowcount": getattr(cursor, "rowcount", len(rows)), "table": params["table"]}

    def _bulk_update(self, connection: Any, params: dict[str, Any]) -> dict[str, Any]:
        rows = params.get("rows") or []
        key_columns = params.get("key_columns") or []
        if not rows or not key_columns:
            raise ValueError("bulk_update requires rows and key_columns")
        update_columns = [column for column in rows[0].keys() if column not in key_columns]
        set_clause = ", ".join(f"{column}={self.placeholder}" for column in update_columns)
        where_clause = " AND ".join(f"{column}={self.placeholder}" for column in key_columns)
        sql = f"UPDATE {params['table']} SET {set_clause} WHERE {where_clause}"
        values = [
            [row.get(column) for column in update_columns] + [row.get(column) for column in key_columns]
            for row in rows
        ]
        cursor = connection.cursor()
        cursor.executemany(sql, values)
        connection.commit()
        return {"rowcount": getattr(cursor, "rowcount", len(rows)), "table": params["table"]}

    async def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        if action == "backup_data":
            return self.backup(params)
        if action == "restore_data":
            return self.restore(params)
        with closing(self.connect(params)) as connection:
            if action == "execute_query":
                return self._execute_query(connection, params)
            if action == "bulk_insert":
                return self._bulk_insert(connection, params)
            if action == "bulk_update":
                return self._bulk_update(connection, params)
        raise ValueError(f"Unsupported database action: {action}")


def _sqlite_path(database_url: str) -> str:
    if database_url == "sqlite:///:memory:":
        return ":memory:"
    if database_url.startswith("sqlite:///"):
        return database_url.removeprefix("sqlite:///")
    raise ValueError("SQLite URLs must use sqlite:///...")


class SqliteAdapter(DatabaseAdapter):
    provider_name = "sqlite"

    def connect(self, params: dict[str, Any]) -> sqlite3.Connection:
        path = _sqlite_path(params["database_url"])
        if path != ":memory:":
            Path(path).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        connection.row_factory = sqlite3.Row
        return connection

    def backup(self, params: dict[str, Any]) -> dict[str, Any]:
        source = Path(_sqlite_path(params["database_url"])).expanduser().resolve()
        destination = Path(params["output_path"]).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"database_url": params["database_url"], "output_path": str(destination)}

    def restore(self, params: dict[str, Any]) -> dict[str, Any]:
        source = Path(params["source_path"]).expanduser().resolve()
        destination = Path(_sqlite_path(params["database_url"])).expanduser().resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {"database_url": params["database_url"], "source_path": str(source)}


def _odbc_connection_string(params: dict[str, Any]) -> str:
    if params.get("connection_string"):
        return str(params["connection_string"])
    database_url = str(params.get("database_url") or "")
    if database_url.startswith("odbc:///?"):
        query = urlparse(database_url).query
        parsed = parse_qs(query)
        value = parsed.get("connection_string", [None])[0]
        if value:
            return unquote(value)
    if database_url.startswith("odbc://"):
        return unquote(database_url.removeprefix("odbc://"))
    raise ValueError("ODBC operations require connection_string or an odbc:// database_url")


class OdbcAdapter(DatabaseAdapter):
    provider_name = "odbc"

    def connect(self, params: dict[str, Any]) -> Any:
        try:
            pyodbc = importlib.import_module("pyodbc")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("odbc provider requires pyodbc to be installed") from exc
        timeout = int(params.get("connect_timeout_s", 15))
        return pyodbc.connect(_odbc_connection_string(params), timeout=timeout)


class JdbcAdapter(DatabaseAdapter):
    provider_name = "jdbc"

    def connect(self, params: dict[str, Any]) -> Any:
        try:
            jaydebeapi = importlib.import_module("jaydebeapi")
        except ImportError as exc:  # pragma: no cover - environment dependent
            raise RuntimeError("jdbc provider requires jaydebeapi to be installed") from exc

        jdbc_url = str(params.get("jdbc_url") or params.get("database_url") or "")
        if not jdbc_url.startswith("jdbc:"):
            raise ValueError("JDBC operations require jdbc_url or a jdbc: database_url")
        driver_class = params.get("driver_class")
        if not driver_class:
            raise ValueError("jdbc provider requires driver_class")

        username = params.get("username")
        password = params.get("password")
        credentials: list[str] | None = None
        if username is not None or password is not None:
            credentials = [str(username or ""), str(password or "")]

        jars = params.get("jars") or params.get("jar")
        if jars is None:
            jars = []
        return jaydebeapi.connect(driver_class, jdbc_url, credentials, jars)


def _provider_for(params: dict[str, Any]) -> DatabaseAdapter:
    provider = str(params.get("provider") or "").strip().lower()
    database_url = str(params.get("database_url") or "").strip().lower()

    if not provider:
        if database_url.startswith("sqlite:"):
            provider = "sqlite"
        elif database_url.startswith("odbc://"):
            provider = "odbc"
        elif database_url.startswith("jdbc:"):
            provider = "jdbc"
        elif params.get("connection_string"):
            provider = "odbc"
        elif params.get("jdbc_url"):
            provider = "jdbc"
        else:
            provider = PROVIDER_SETTINGS.provider.strip().lower()

    if provider in {"sqlite", "sqlite3"}:
        return SqliteAdapter()
    if provider == "odbc":
        return OdbcAdapter()
    if provider == "jdbc":
        return JdbcAdapter()
    raise ValueError(f"Unknown database provider: {provider}")


async def _execute(action: str, params: dict[str, Any], req: AgentExecuteRequest) -> dict[str, Any]:
    adapter = _provider_for(params)
    result = await adapter.execute(action, params)
    result.setdefault("provider", adapter.provider_name)
    return result


app = build_agent_app(
    title="LangOrch Database Automation Agent",
    version="0.3.0",
    settings=SETTINGS,
    capabilities=CAPABILITIES,
    execute_handler=_execute,
    health_provider=lambda: {"provider": PROVIDER_SETTINGS.provider},
    session_store=SESSION_STORE,
)
