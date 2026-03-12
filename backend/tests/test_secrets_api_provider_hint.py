from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.api.auth import _issue_jwt
from app.config import settings
from app.main import app


def _auth_headers(role: str) -> dict[str, str]:
    token = _issue_jwt(f"test-{role}", [role], 60, settings.AUTH_SECRET_KEY)
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _auth_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "secrets-tests-secret-with-at-least-32-bytes")


@pytest.fixture(autouse=True)
def _encryption_key(monkeypatch):
    pytest.importorskip("cryptography.fernet")
    from cryptography.fernet import Fernet

    monkeypatch.setenv("SECRETS_ENCRYPTION_KEY", Fernet.generate_key().decode())


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.mark.asyncio
async def test_secret_provider_hint_can_be_updated(client: AsyncClient):
    create_resp = await client.post(
        "/api/secrets",
        json={"name": "provider-hint-secret", "value": "super-secret", "provider_hint": "db"},
        headers=_auth_headers("admin"),
    )
    assert create_resp.status_code == 201, create_resp.text

    update_resp = await client.put(
        "/api/secrets/provider-hint-secret",
        json={"provider_hint": "vault"},
        headers=_auth_headers("admin"),
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["provider_hint"] == "vault"

    get_resp = await client.get(
        "/api/secrets/provider-hint-secret",
        headers=_auth_headers("operator"),
    )
    assert get_resp.status_code == 200, get_resp.text
    assert get_resp.json()["provider_hint"] == "vault"