"""Shared protocol helpers for orchestrator <-> agent communication."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from typing import Any


SIGNATURE_HEADER = "x-agent-signature"
TIMESTAMP_HEADER = "x-agent-timestamp"
TRACE_HEADER = "x-trace-id"
PROTOCOL_HEADER = "x-agent-protocol-version"
ATTEMPT_HEADER = "x-attempt"
RUN_HEADER = "x-run-id"
NODE_HEADER = "x-node-id"
STEP_HEADER = "x-step-id"
TENANT_HEADER = "x-tenant-id"
IDEMPOTENCY_HEADER = "x-idempotency-key"
LEASE_HEADER = "x-lease-id"


def generate_trace_id() -> str:
    return uuid.uuid4().hex


def canonical_json_bytes(payload: Any) -> bytes:
    if payload is None:
        return b""
    if isinstance(payload, bytes):
        try:
            payload = json.loads(payload.decode("utf-8"))
        except Exception:
            return payload
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _signature_payload(method: str, path: str, timestamp: str, body: bytes) -> bytes:
    body_hash = hashlib.sha256(body).hexdigest()
    return f"{method.upper()}|{path}|{timestamp}|{body_hash}".encode("utf-8")


def sign_request(method: str, path: str, body: Any, secret: str, timestamp: str | None = None) -> tuple[str, str]:
    ts = timestamp or str(int(time.time()))
    canonical_body = canonical_json_bytes(body)
    digest = hmac.new(
        secret.encode("utf-8"),
        _signature_payload(method, path, ts, canonical_body),
        hashlib.sha256,
    ).hexdigest()
    return ts, f"sha256={digest}"


def build_signed_headers(
    method: str,
    path: str,
    body: Any,
    secret: str | None,
    extra_headers: dict[str, str] | None = None,
) -> dict[str, str]:
    headers = dict(extra_headers or {})
    if not secret:
        return headers
    timestamp, signature = sign_request(method, path, body, secret)
    headers[TIMESTAMP_HEADER] = timestamp
    headers[SIGNATURE_HEADER] = signature
    return headers


def verify_signed_request(
    *,
    method: str,
    path: str,
    body: Any,
    secret: str | None,
    provided_timestamp: str | None,
    provided_signature: str | None,
    ttl_seconds: int,
) -> bool:
    if not secret:
        return True
    if not provided_timestamp or not provided_signature:
        return False
    try:
        timestamp_int = int(provided_timestamp)
    except ValueError:
        return False
    if abs(int(time.time()) - timestamp_int) > ttl_seconds:
        return False
    _, expected_signature = sign_request(method, path, body, secret, timestamp=provided_timestamp)
    return hmac.compare_digest(expected_signature, provided_signature)
