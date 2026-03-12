from __future__ import annotations

import hashlib
import hmac

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import _issue_jwt
from app.config import settings
from app.db.engine import async_session
from app.main import app
from app.services import procedure_service, trigger_service


def _auth_headers(role: str) -> dict[str, str]:
    token = _issue_jwt(f"test-{role}", [role], 60, settings.AUTH_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


def _make_ckp(procedure_id: str, version: str) -> dict:
    return {
        "procedure_id": procedure_id,
        "version": version,
        "global_config": {},
        "variables_schema": {},
        "workflow_graph": {
            "start_node": "start",
            "nodes": {
                "start": {
                    "type": "sequence",
                    "next_node": "end",
                    "steps": [{"step_id": "log", "action": "log", "message": "hello"}],
                },
                "end": {"type": "terminate", "status": "success"},
            },
        },
    }


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "trigger-tests-secret-with-at-least-32-bytes")


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_trigger_endpoints_require_auth(client: AsyncClient):
    list_resp = await client.get("/api/triggers")
    assert list_resp.status_code == 401

    create_resp = await client.post(
        "/api/triggers/proc/1.0.0",
        json={"trigger_type": "webhook", "webhook_secret": "TEST_SECRET"},
    )
    assert create_resp.status_code == 401


@pytest.mark.asyncio
async def test_operator_cannot_register_or_delete_trigger(client: AsyncClient):
    create_resp = await client.post(
        "/api/triggers/proc/1.0.0",
        json={"trigger_type": "webhook", "webhook_secret": "TEST_SECRET"},
        headers=_auth_headers("operator"),
    )
    assert create_resp.status_code == 403

    delete_resp = await client.delete(
        "/api/triggers/proc/1.0.0",
        headers=_auth_headers("operator"),
    )
    assert delete_resp.status_code == 403


@pytest.mark.asyncio
async def test_manager_can_register_and_operator_can_read_and_fire_trigger(client: AsyncClient):
    procedure_id = "trigger_rbac_proc"

    async with async_session() as db:
        await procedure_service.import_procedure(db, _make_ckp(procedure_id, "1.0.0"))
        await db.commit()

    create_resp = await client.post(
        f"/api/triggers/{procedure_id}/1.0.0",
        json={"trigger_type": "scheduled", "schedule": "0 9 * * 1-5", "enabled": True},
        headers=_auth_headers("manager"),
    )
    assert create_resp.status_code == 201, create_resp.text

    get_resp = await client.get(
        f"/api/triggers/{procedure_id}/1.0.0",
        headers=_auth_headers("operator"),
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["schedule"] == "0 9 * * 1-5"

    fire_resp = await client.post(
        f"/api/triggers/{procedure_id}/1.0.0/fire",
        headers=_auth_headers("operator"),
    )
    assert fire_resp.status_code == 202, fire_resp.text
    assert fire_resp.json()["procedure_id"] == procedure_id


@pytest.mark.asyncio
async def test_trigger_registration_rejects_webhook_without_secret(client: AsyncClient):
    resp = await client.post(
        "/api/triggers/proc/1.0.0",
        json={"trigger_type": "webhook"},
        headers=_auth_headers("manager"),
    )
    assert resp.status_code == 422
    assert "webhook_secret" in resp.text


@pytest.mark.asyncio
async def test_trigger_registration_rejects_invalid_schedule(client: AsyncClient):
    resp = await client.post(
        "/api/triggers/proc/1.0.0",
        json={"trigger_type": "scheduled", "schedule": "bad cron"},
        headers=_auth_headers("manager"),
    )
    assert resp.status_code == 422
    assert "Cron schedule" in resp.text or "cron" in resp.text.lower()


@pytest.mark.asyncio
async def test_webhook_uses_latest_updated_webhook_trigger(client: AsyncClient, monkeypatch):
    procedure_id = "webhook_version_pick"
    monkeypatch.setenv("WEBHOOK_SECRET_V1", "secret-v1")
    monkeypatch.setenv("WEBHOOK_SECRET_V2", "secret-v2")

    async with async_session() as db:
        await procedure_service.import_procedure(db, _make_ckp(procedure_id, "1.0.0"))
        await procedure_service.import_procedure(db, _make_ckp(procedure_id, "2.0.0"))
        await trigger_service.upsert_trigger(
            db,
            procedure_id,
            "1.0.0",
            override={"trigger_type": "webhook", "webhook_secret": "WEBHOOK_SECRET_V1", "enabled": True},
        )
        await trigger_service.upsert_trigger(
            db,
            procedure_id,
            "2.0.0",
            override={"trigger_type": "webhook", "webhook_secret": "WEBHOOK_SECRET_V2", "enabled": True},
        )
        await db.commit()

    body = b'{"source":"latest"}'
    signature = hmac.new(b"secret-v2", body, hashlib.sha256).hexdigest()

    resp = await client.post(
        f"/api/triggers/webhook/{procedure_id}",
        content=body,
        headers={"X-LangOrch-Signature": f"sha256={signature}"},
    )

    assert resp.status_code == 202, resp.text
    payload = resp.json()
    assert payload["procedure_version"] == "2.0.0"


def test_verify_hmac_signature_fails_closed_without_env(monkeypatch):
    monkeypatch.delenv("MISSING_SECRET", raising=False)

    assert trigger_service.verify_hmac_signature(b"body", "sha256=abc", "MISSING_SECRET") is False
