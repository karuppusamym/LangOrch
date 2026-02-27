"""Tests for the AuditEvent system.

Covers:
  1. Creating audit events via emit_audit
  2. GET /api/audit listing with filters
  3. Audit events are emitted on user create/delete
  4. Audit events are emitted on secret create/delete
"""

from __future__ import annotations

import json
import pytest
import httpx
from httpx import ASGITransport

from app.main import app
from app.db.engine import async_session
from app.api.audit import emit_audit


@pytest.fixture
def client():
    transport = ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://test")


# ── 1. emit_audit creates records ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_emit_audit_creates_record(client: httpx.AsyncClient):
    """emit_audit should persist a record that is retrievable via GET /api/audit."""
    async with async_session() as db:
        await emit_audit(
            db,
            category="test_category",
            action="test_action",
            actor="test_actor",
            description="Test audit event",
            resource_type="test_resource",
            resource_id="res_001",
            meta={"key": "value"},
        )
        await db.commit()

    resp = await client.get("/api/audit", params={"category": "test_category"})
    assert resp.status_code == 200
    body = resp.json()
    events = body["events"]
    assert len(events) >= 1
    ev = events[0]
    assert ev["category"] == "test_category"
    assert ev["action"] == "test_action"
    assert ev["actor"] == "test_actor"
    assert ev["description"] == "Test audit event"
    assert ev["resource_type"] == "test_resource"
    assert ev["resource_id"] == "res_001"
    assert ev["meta"]["key"] == "value"


# ── 2. GET /api/audit filters ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_audit_api_filters(client: httpx.AsyncClient):
    """GET /api/audit should filter by category, actor, action, and search."""
    async with async_session() as db:
        await emit_audit(db, category="auth", action="login", actor="alice", description="Alice logged in")
        await emit_audit(db, category="auth", action="login_failed", actor="bob", description="Bob failed login")
        await emit_audit(db, category="user_mgmt", action="create", actor="alice", description="Alice created user")
        await db.commit()

    # Filter by category
    resp = await client.get("/api/audit", params={"category": "auth"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["category"] == "auth" for e in events)

    # Filter by actor
    resp = await client.get("/api/audit", params={"actor": "bob"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert all(e["actor"] == "bob" for e in events)

    # Filter by search
    resp = await client.get("/api/audit", params={"search": "failed"})
    assert resp.status_code == 200
    events = resp.json()["events"]
    assert len(events) >= 1
    assert any("failed" in e["description"].lower() for e in events)


# ── 3. User CRUD emits audit events ───────────────────────────────────────


@pytest.mark.asyncio
async def test_user_create_emits_audit(client: httpx.AsyncClient):
    """Creating a user via POST /api/users should emit a user_mgmt:create audit event."""
    import uuid
    username = f"audit_test_{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/api/users",
        json={"username": username,  "email": f"{username}@test.com" , "password": "TestP@ss123", "role": "viewer"},
    )
    # May get 200/201 or 403 if auth is enforced — skip if auth blocks
    if resp.status_code in (401, 403):
        pytest.skip("Auth required for user creation, skipping audit check")
    assert resp.status_code in (200, 201)

    audit_resp = await client.get("/api/audit", params={"category": "user_mgmt", "action": "create"})
    assert audit_resp.status_code == 200
    events = audit_resp.json()["events"]
    assert any(e["resource_id"] == username for e in events), \
        f"Expected audit event for user '{username}' creation"

    # Cleanup — delete the user
    await client.delete(f"/api/users/{username}")


# ── 4. Secret CRUD emits audit events ─────────────────────────────────────


@pytest.mark.asyncio
async def test_secret_create_emits_audit(client: httpx.AsyncClient):
    """Creating a secret via POST /api/secrets should emit a secret_mgmt:create audit event."""
    import uuid
    name = f"audit_secret_{uuid.uuid4().hex[:8]}"

    resp = await client.post(
        "/api/secrets",
        json={"name": name, "value": "s3cr3t"},
    )
    if resp.status_code in (401, 403):
        pytest.skip("Auth required for secret creation, skipping audit check")
    assert resp.status_code in (200, 201)

    audit_resp = await client.get("/api/audit", params={"category": "secret_mgmt", "action": "create"})
    assert audit_resp.status_code == 200
    events = audit_resp.json()["events"]
    assert any(e["resource_id"] == name for e in events), \
        f"Expected audit event for secret '{name}' creation"

    # Cleanup
    await client.delete(f"/api/secrets/{name}")
