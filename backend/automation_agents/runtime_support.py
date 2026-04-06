"""Shared validation, policy, and session helpers for automation agents."""

from __future__ import annotations

import asyncio
import os
import re
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from app.config import settings as orch_settings
from app.contracts.agent_contracts import AgentCapability, AgentExecuteRequest


def object_schema(
    *,
    required: list[str] | None = None,
    properties: dict[str, Any] | None = None,
    additional_properties: bool = True,
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": required or [],
        "properties": properties or {},
        "additionalProperties": additional_properties,
    }


def array_schema(items: dict[str, Any]) -> dict[str, Any]:
    return {"type": "array", "items": items}


def string_schema(*, enum: list[str] | None = None) -> dict[str, Any]:
    schema: dict[str, Any] = {"type": "string"}
    if enum:
        schema["enum"] = enum
    return schema


def validate_json_schema(schema: dict[str, Any] | None, payload: Any, label: str) -> None:
    if not schema:
        return
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(payload), key=lambda item: list(item.absolute_path))
    if errors:
        err = errors[0]
        path = ".".join(str(part) for part in err.absolute_path) or "<root>"
        raise ValueError(f"{label} schema validation failed at {path}: {err.message}")


@dataclass
class PolicyDecision:
    allowed: bool
    warnings: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    matched_patterns: list[str] = field(default_factory=list)
    rule_hits: list[dict[str, Any]] = field(default_factory=list)
    risk_level: str = "none"

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "warnings": self.warnings,
            "reasons": self.reasons,
            "matched_patterns": self.matched_patterns,
            "rule_hits": self.rule_hits,
            "risk_level": self.risk_level,
        }


_EMAIL_RE = re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.IGNORECASE)
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_CARD_RE = re.compile(r"\b(?:\d[ -]*?){13,16}\b")


def _iter_text(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for item in value.values():
            yield from _iter_text(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _iter_text(item)


def _find_pii_markers(params: dict[str, Any]) -> list[str]:
    markers: list[str] = []
    for text in _iter_text(params):
        if _EMAIL_RE.search(text):
            markers.append("email")
        if _SSN_RE.search(text):
            markers.append("ssn")
        if _CARD_RE.search(text):
            markers.append("payment_card")
    return sorted(set(markers))


def evaluate_policy(capability: AgentCapability | None, params: dict[str, Any], req: AgentExecuteRequest) -> PolicyDecision:
    if not orch_settings.AGENT_POLICY_ENFORCEMENT or capability is None:
        return PolicyDecision(allowed=True)

    side_effect_level = capability.side_effect_level or "none"
    is_write = side_effect_level in {"low", "medium", "high"}
    reasons: list[str] = []
    warnings: list[str] = []
    matched_patterns: list[str] = []
    rule_hits: list[dict[str, Any]] = []

    if is_write and orch_settings.AGENT_POLICY_REQUIRE_TENANT_FOR_SIDE_EFFECTS and not req.tenant_id:
        reasons.append("tenant_id is required for side-effecting actions")
        rule_hits.append({"rule": "require_tenant_for_side_effects", "outcome": "blocked"})

    if (capability.requires_approval or side_effect_level == "high") and orch_settings.AGENT_POLICY_REQUIRE_APPROVAL_FOR_HIGH_RISK:
        if not req.approval_id and not params.get("approval_id"):
            reasons.append("approval_id is required for high-risk side-effecting actions")
            rule_hits.append({"rule": "require_approval_for_high_risk", "outcome": "blocked"})

    forbidden_patterns = list(orch_settings.AGENT_POLICY_FORBIDDEN_TARGET_PATTERNS or [])
    if forbidden_patterns:
        haystack = " ".join(_iter_text(params)).lower()
        for pattern in forbidden_patterns:
            if pattern and pattern.lower() in haystack:
                matched_patterns.append(pattern)
        if matched_patterns:
            reasons.append(f"forbidden target pattern matched: {', '.join(sorted(set(matched_patterns)))}")
            rule_hits.append({"rule": "forbidden_target_patterns", "outcome": "blocked", "matches": sorted(set(matched_patterns))})

    url_patterns = list(orch_settings.AGENT_POLICY_FORBIDDEN_URL_PATTERNS or [])
    url_values = [value for key, value in params.items() if "url" in str(key).lower() and isinstance(value, str)]
    url_matches = [pattern for pattern in url_patterns for value in url_values if pattern and pattern.lower() in value.lower()]
    if url_matches:
        reasons.append(f"forbidden url pattern matched: {', '.join(sorted(set(url_matches)))}")
        rule_hits.append({"rule": "forbidden_url_patterns", "outcome": "blocked", "matches": sorted(set(url_matches))})

    file_patterns = list(orch_settings.AGENT_POLICY_FORBIDDEN_FILE_PATH_PATTERNS or [])
    file_values = [value for key, value in params.items() if "path" in str(key).lower() and isinstance(value, str)]
    file_matches = [pattern for pattern in file_patterns for value in file_values if pattern and pattern.lower() in value.lower()]
    if file_matches:
        reasons.append(f"forbidden file path pattern matched: {', '.join(sorted(set(file_matches)))}")
        rule_hits.append({"rule": "forbidden_file_path_patterns", "outcome": "blocked", "matches": sorted(set(file_matches))})

    table_patterns = list(orch_settings.AGENT_POLICY_FORBIDDEN_DB_TABLE_PATTERNS or [])
    table_name = str(params.get("table") or "")
    table_matches = [pattern for pattern in table_patterns if pattern and pattern.lower() in table_name.lower()]
    if table_matches:
        reasons.append(f"forbidden database table matched: {', '.join(sorted(set(table_matches)))}")
        rule_hits.append({"rule": "forbidden_db_table_patterns", "outcome": "blocked", "matches": sorted(set(table_matches))})

    allowed_domains = [domain.lower() for domain in (orch_settings.AGENT_POLICY_ALLOWED_EMAIL_DOMAINS or []) if domain]
    if allowed_domains:
        email_values = []
        for key, value in params.items():
            if key.lower() in {"to", "cc", "bcc", "from"}:
                if isinstance(value, str):
                    email_values.append(value)
                elif isinstance(value, list):
                    email_values.extend([item for item in value if isinstance(item, str)])
        bad_domains = []
        for address in email_values:
            if "@" in address:
                domain = address.rsplit("@", 1)[-1].lower()
                if domain not in allowed_domains:
                    bad_domains.append(domain)
        if bad_domains:
            reasons.append(f"email domain not allowed: {', '.join(sorted(set(bad_domains)))}")
            rule_hits.append({"rule": "allowed_email_domains", "outcome": "blocked", "matches": sorted(set(bad_domains))})

    pii_markers = _find_pii_markers(params)
    if pii_markers:
        warnings.append(f"PII markers detected: {', '.join(pii_markers)}")
        if is_write and orch_settings.AGENT_POLICY_BLOCK_PII_WITHOUT_APPROVAL and not req.approval_id and not params.get("allow_pii"):
            reasons.append("PII detected in side-effecting request without approval_id or allow_pii")
            rule_hits.append({"rule": "block_pii_without_approval", "outcome": "blocked", "matches": pii_markers})

    if warnings and not any(hit["rule"] == "pii_warning" for hit in rule_hits):
        rule_hits.append({"rule": "pii_warning", "outcome": "warned", "matches": pii_markers})

    return PolicyDecision(
        allowed=not reasons,
        warnings=warnings,
        reasons=reasons,
        matched_patterns=matched_patterns,
        rule_hits=rule_hits,
        risk_level=side_effect_level,
    )


@dataclass
class SessionEntry:
    session_id: str
    data: dict[str, Any]
    created_at: float
    last_used_at: float
    expires_at: float

    def snapshot(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "created_at": self.created_at,
            "last_used_at": self.last_used_at,
            "expires_at": self.expires_at,
            "data": self.data,
        }


class SessionStore:
    backend = "memory"

    def __init__(self, timeout_s: int = 1800):
        self.timeout_s = timeout_s
        self._entries: dict[str, SessionEntry] = {}
        self._lock = asyncio.Lock()

    async def create(self, data: dict[str, Any]) -> SessionEntry:
        async with self._lock:
            now = time.time()
            session_id = uuid.uuid4().hex
            entry = SessionEntry(
                session_id=session_id,
                data=dict(data),
                created_at=now,
                last_used_at=now,
                expires_at=now + self.timeout_s,
            )
            self._entries[session_id] = entry
            return entry

    async def get(self, session_id: str) -> SessionEntry | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= time.time():
                self._entries.pop(session_id, None)
                return None
            entry.last_used_at = time.time()
            entry.expires_at = entry.last_used_at + self.timeout_s
            return entry

    async def update(self, session_id: str, data: dict[str, Any]) -> SessionEntry | None:
        async with self._lock:
            entry = self._entries.get(session_id)
            if entry is None:
                return None
            if entry.expires_at <= time.time():
                self._entries.pop(session_id, None)
                return None
            entry.data.update(data)
            entry.last_used_at = time.time()
            entry.expires_at = entry.last_used_at + self.timeout_s
            return entry

    async def close(self, session_id: str) -> SessionEntry | None:
        async with self._lock:
            return self._entries.pop(session_id, None)

    async def cleanup_expired(self) -> int:
        async with self._lock:
            now = time.time()
            expired = [session_id for session_id, entry in self._entries.items() if entry.expires_at <= now]
            for session_id in expired:
                self._entries.pop(session_id, None)
            return len(expired)

    async def count(self) -> int:
        await self.cleanup_expired()
        async with self._lock:
            return len(self._entries)


class DbSessionStore:
    backend = "db"

    def __init__(self, *, agent_id: str, channel: str, timeout_s: int = 1800):
        self.agent_id = agent_id
        self.channel = channel
        self.timeout_s = timeout_s

    async def create(self, data: dict[str, Any]) -> SessionEntry:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            row = await automation_session_service.create_session(
                db,
                agent_id=self.agent_id,
                channel=self.channel,
                timeout_s=self.timeout_s,
                data=data,
                run_id=str(data.get("run_id")) if data.get("run_id") is not None else None,
                tenant_id=str(data.get("tenant_id")) if data.get("tenant_id") is not None else None,
                user_id=str(data.get("user_id")) if data.get("user_id") is not None else None,
            )
            await db.commit()
            return SessionEntry(
                session_id=row.session_id,
                data=automation_session_service.session_snapshot(row)["data"],
                created_at=row.created_at.timestamp(),
                last_used_at=row.last_used_at.timestamp(),
                expires_at=row.expires_at.timestamp(),
            )

    async def get(self, session_id: str) -> SessionEntry | None:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            row = await automation_session_service.get_session(db, session_id, timeout_s=self.timeout_s)
            if row is None or row.agent_id != self.agent_id:
                await db.commit()
                return None
            await db.commit()
            snap = automation_session_service.session_snapshot(row)
            return SessionEntry(
                session_id=row.session_id,
                data=snap["data"],
                created_at=snap["created_at"],
                last_used_at=snap["last_used_at"],
                expires_at=snap["expires_at"],
            )

    async def update(self, session_id: str, data: dict[str, Any]) -> SessionEntry | None:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            row = await automation_session_service.update_session(db, session_id, timeout_s=self.timeout_s, data=data)
            if row is None or row.agent_id != self.agent_id:
                await db.commit()
                return None
            await db.commit()
            snap = automation_session_service.session_snapshot(row)
            return SessionEntry(
                session_id=row.session_id,
                data=snap["data"],
                created_at=snap["created_at"],
                last_used_at=snap["last_used_at"],
                expires_at=snap["expires_at"],
            )

    async def close(self, session_id: str) -> SessionEntry | None:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            row = await automation_session_service.close_session(db, session_id)
            if row is None or row.agent_id != self.agent_id:
                await db.commit()
                return None
            await db.commit()
            snap = automation_session_service.session_snapshot(row)
            return SessionEntry(
                session_id=row.session_id,
                data=snap["data"],
                created_at=snap["created_at"],
                last_used_at=snap["last_used_at"],
                expires_at=snap["expires_at"],
            )

    async def cleanup_expired(self) -> int:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            deleted = await automation_session_service.cleanup_expired_sessions(db, agent_id=self.agent_id, channel=self.channel)
            await db.commit()
            return deleted

    async def count(self) -> int:
        from app.db.engine import async_session
        from app.services import automation_session_service

        async with async_session() as db:
            count = await automation_session_service.count_active_sessions(db, agent_id=self.agent_id, channel=self.channel)
            await db.commit()
            return count


def build_session_store(*, agent_id: str, channel: str, timeout_s: int) -> SessionStore | DbSessionStore:
    backend = os.getenv("AGENT_SESSION_BACKEND", "db").strip().lower()
    if backend == "memory":
        return SessionStore(timeout_s=timeout_s)
    return DbSessionStore(agent_id=agent_id, channel=channel, timeout_s=timeout_s)
