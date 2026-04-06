"""Filesystem automation agent with safe, generic file operations."""

from __future__ import annotations

import json
import mimetypes
import os
import shutil
import zipfile
from pathlib import Path
from typing import Any

from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest

from automation_agents.shared import AutomationAgentSettings, build_agent_app
from automation_agents.runtime_support import array_schema, object_schema, string_schema


def _as_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


SETTINGS = AutomationAgentSettings(
    orchestrator_url=os.getenv("ORCHESTRATOR_URL", "http://127.0.0.1:8000"),
    agent_id=os.getenv("FILE_AGENT_ID", "file-automation-agent"),
    agent_name=os.getenv("FILE_AGENT_NAME", "File Automation Agent"),
    agent_port=int(os.getenv("FILE_AGENT_PORT", "9012")),
    channel=os.getenv("FILE_AGENT_CHANNEL", "file"),
    pool_id=os.getenv("FILE_AGENT_POOL_ID", "file_pool"),
    resource_key=os.getenv("FILE_AGENT_RESOURCE_KEY", "file_default"),
    concurrency_limit=int(os.getenv("FILE_AGENT_CONCURRENCY", "4")),
    description="Safe file and directory automation with optional workspace confinement.",
)

BASE_DIR = os.getenv("FILE_AGENT_BASE_DIR")
ALLOW_DELETE = _as_bool(os.getenv("FILE_AGENT_ALLOW_DELETE"), False)

CAPABILITIES = [
    AgentCapability(
        name="read_file",
        description="Read text or JSON files",
        input_schema=object_schema(required=["path"], properties={"path": string_schema(), "mode": string_schema(enum=["text", "json"])}),
        output_schema=object_schema(required=["path", "content"], properties={"path": string_schema()}),
        side_effect_level="none",
        idempotent=True,
    ),
    AgentCapability(
        name="write_file",
        description="Write text or JSON files",
        input_schema=object_schema(required=["path", "content"], properties={"path": string_schema()}),
        output_schema=object_schema(required=["path", "bytes_written"], properties={"path": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
    ),
    AgentCapability(
        name="list_directory",
        description="List directory contents",
        input_schema=object_schema(required=["path"], properties={"path": string_schema()}),
        output_schema=object_schema(required=["path", "entries", "count"], properties={"path": string_schema(), "entries": array_schema(object_schema())}),
        side_effect_level="none",
        idempotent=True,
    ),
    AgentCapability(
        name="create_directory",
        description="Create directories",
        input_schema=object_schema(required=["path"], properties={"path": string_schema()}),
        output_schema=object_schema(required=["path", "created"], properties={"path": string_schema()}),
        side_effect_level="medium",
        idempotent=False,
    ),
    AgentCapability(
        name="copy_file",
        description="Copy files",
        input_schema=object_schema(required=["source_path", "destination_path"], properties={"source_path": string_schema(), "destination_path": string_schema()}),
        output_schema=object_schema(required=["source_path", "destination_path"], properties={"source_path": string_schema(), "destination_path": string_schema()}),
        side_effect_level="high",
        idempotent=False,
    ),
    AgentCapability(
        name="move_file",
        description="Move files",
        input_schema=object_schema(required=["source_path", "destination_path"], properties={"source_path": string_schema(), "destination_path": string_schema()}),
        output_schema=object_schema(required=["source_path", "destination_path"], properties={"source_path": string_schema(), "destination_path": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
    ),
    AgentCapability(
        name="delete_file",
        description="Delete files or directories when enabled",
        input_schema=object_schema(required=["path"], properties={"path": string_schema()}),
        output_schema=object_schema(required=["path", "deleted"], properties={"path": string_schema()}),
        side_effect_level="high",
        idempotent=False,
        requires_approval=True,
    ),
    AgentCapability(
        name="zip_files",
        description="Create zip archives",
        input_schema=object_schema(required=["output_path", "paths"], properties={"output_path": string_schema(), "paths": array_schema(string_schema())}),
        output_schema=object_schema(required=["output_path", "archived_paths"], properties={"output_path": string_schema(), "archived_paths": array_schema(string_schema())}),
        side_effect_level="medium",
        idempotent=False,
    ),
    AgentCapability(
        name="unzip_files",
        description="Extract zip archives",
        input_schema=object_schema(required=["archive_path", "output_dir"], properties={"archive_path": string_schema(), "output_dir": string_schema()}),
        output_schema=object_schema(required=["archive_path", "output_dir", "entries"], properties={"archive_path": string_schema(), "output_dir": string_schema(), "entries": array_schema(string_schema())}),
        side_effect_level="medium",
        idempotent=False,
    ),
]


def _resolve_path(raw_path: str) -> Path:
    path = Path(raw_path).expanduser()
    if BASE_DIR:
        base = Path(BASE_DIR).expanduser().resolve()
        candidate = (base / path).resolve() if not path.is_absolute() else path.resolve()
        if base != candidate and base not in candidate.parents:
            raise ValueError(f"Path '{candidate}' escapes FILE_AGENT_BASE_DIR")
        return candidate
    return path.resolve() if path.exists() else path.expanduser().absolute()


def _serialize_entry(entry: Path) -> dict[str, Any]:
    stat = entry.stat()
    return {
        "name": entry.name,
        "path": str(entry),
        "is_dir": entry.is_dir(),
        "size_bytes": stat.st_size,
    }


def _artifact_kind_for_path(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".json"}:
        return "json"
    if suffix in {".txt", ".md", ".log", ".csv", ".xml", ".yaml", ".yml"}:
        return "text"
    if suffix in {".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp"}:
        return "image"
    if suffix in {".zip"}:
        return "archive"
    return "file"


def _artifact_payload(path: Path) -> dict[str, Any]:
    mime_type, _ = mimetypes.guess_type(path.name)
    return {
        "kind": _artifact_kind_for_path(path),
        "uri": str(path),
        "name": path.name,
        "mime_type": mime_type,
        "size_bytes": path.stat().st_size if path.exists() else None,
    }


async def _execute(action: str, params: dict[str, Any], req: AgentExecuteRequest) -> dict[str, Any]:
    if action == "read_file":
        path = _resolve_path(params["path"])
        mode = str(params.get("mode", "text")).lower()
        encoding = params.get("encoding", "utf-8")
        if mode == "json":
            return {"path": str(path), "content": json.loads(path.read_text(encoding=encoding))}
        return {"path": str(path), "content": path.read_text(encoding=encoding)}

    if action == "write_file":
        path = _resolve_path(params["path"])
        path.parent.mkdir(parents=True, exist_ok=True)
        content = params.get("content", "")
        encoding = params.get("encoding", "utf-8")
        if isinstance(content, (dict, list)):
            text = json.dumps(content, indent=2)
        else:
            text = str(content)
        path.write_text(text, encoding=encoding)
        return {
            "path": str(path),
            "bytes_written": len(text.encode(encoding)),
            "artifact": _artifact_payload(path),
        }

    if action == "list_directory":
        path = _resolve_path(params["path"])
        recursive = bool(params.get("recursive", False))
        iterator = path.rglob("*") if recursive else path.iterdir()
        entries = [_serialize_entry(entry) for entry in iterator]
        return {"path": str(path), "entries": entries, "count": len(entries)}

    if action == "create_directory":
        path = _resolve_path(params["path"])
        path.mkdir(parents=True, exist_ok=True)
        return {"path": str(path), "created": True}

    if action == "copy_file":
        source = _resolve_path(params["source_path"])
        destination = _resolve_path(params["destination_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)
        return {
            "source_path": str(source),
            "destination_path": str(destination),
            "artifact": _artifact_payload(destination),
        }

    if action == "move_file":
        source = _resolve_path(params["source_path"])
        destination = _resolve_path(params["destination_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(source), str(destination))
        return {
            "source_path": str(source),
            "destination_path": str(destination),
            "artifact": _artifact_payload(destination),
        }

    if action == "delete_file":
        if not ALLOW_DELETE:
            raise PermissionError("FILE_AGENT_ALLOW_DELETE is false")
        path = _resolve_path(params["path"])
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=False)
        return {"path": str(path), "deleted": True}

    if action == "zip_files":
        output_path = _resolve_path(params["output_path"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        sources = [_resolve_path(item) for item in params.get("paths", [])]
        with zipfile.ZipFile(output_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for source in sources:
                archive.write(source, arcname=source.name)
        return {
            "output_path": str(output_path),
            "archived_paths": [str(path) for path in sources],
            "artifact": _artifact_payload(output_path),
        }

    if action == "unzip_files":
        archive_path = _resolve_path(params["archive_path"])
        output_dir = _resolve_path(params["output_dir"])
        output_dir.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(archive_path, "r") as archive:
            archive.extractall(output_dir)
            names = archive.namelist()
        return {"archive_path": str(archive_path), "output_dir": str(output_dir), "entries": names}

    raise ValueError(f"Unsupported file action: {action}")


app = build_agent_app(
    title="LangOrch File Automation Agent",
    version="0.1.0",
    settings=SETTINGS,
    capabilities=CAPABILITIES,
    execute_handler=_execute,
    health_provider=lambda: {
        "base_dir": BASE_DIR,
        "allow_delete": ALLOW_DELETE,
    },
)
