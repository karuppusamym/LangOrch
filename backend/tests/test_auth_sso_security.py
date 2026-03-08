from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
from httpx import ASGITransport, AsyncClient

from app.api import auth as auth_api
from app.config import settings
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sso_settings(monkeypatch):
    monkeypatch.setattr(settings, "SSO_ENABLED", True)
    monkeypatch.setattr(settings, "SSO_CLIENT_ID", "test-client-id")
    monkeypatch.setattr(settings, "SSO_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setattr(settings, "SSO_AUTHORITY", "https://login.example.com/tenant/v2.0")
    monkeypatch.setattr(settings, "SSO_REDIRECT_URI", "http://test/api/auth/sso/callback")
    monkeypatch.setattr(settings, "FRONTEND_BASE_URL", "http://frontend.local")
    monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "test-auth-secret-with-at-least-32-bytes")
    monkeypatch.setattr(settings, "SSO_ROLE_MAPPING", '{"group-operator": "operator"}')


class _TokenExchangeResponse:
    status_code = 200
    text = "ok"

    def __init__(self, payload: dict):
        self._payload = payload

    def json(self) -> dict:
        return self._payload


class _TokenExchangeClient:
    def __init__(self, payload: dict):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, data: dict):
        return _TokenExchangeResponse(self._payload)


class TestSsoSecurity:
    @pytest.mark.asyncio
    async def test_sso_login_issues_signed_state_and_nonce(self, client, sso_settings):
        response = await client.get("/api/auth/sso/login", follow_redirects=False)

        assert response.status_code in {302, 307}
        location = response.headers["location"]
        parsed = urlparse(location)
        params = parse_qs(parsed.query)

        assert params["client_id"] == [settings.SSO_CLIENT_ID]
        assert "state" in params
        assert "nonce" in params

        decoded_state = auth_api._decode_sso_state(params["state"][0], settings.AUTH_SECRET_KEY)
        assert decoded_state["nonce"] == params["nonce"][0]

    @pytest.mark.asyncio
    async def test_sso_callback_rejects_invalid_state_before_token_exchange(self, client, sso_settings, monkeypatch):
        class _ShouldNotBeCalled:
            def __init__(self, *args, **kwargs):
                raise AssertionError("Token exchange should not be attempted for invalid state")

        monkeypatch.setattr(auth_api.httpx, "AsyncClient", _ShouldNotBeCalled)

        response = await client.get(
            "/api/auth/sso/callback",
            params={"code": "auth-code", "state": "invalid-state"},
        )

        assert response.status_code == 400
        assert response.json()["detail"] == "Invalid or expired SSO state"

    @pytest.mark.asyncio
    async def test_sso_callback_provisions_user_after_verified_id_token(self, client, sso_settings, monkeypatch):
        nonce = "nonce-123"
        state = auth_api._issue_sso_state(settings.AUTH_SECRET_KEY, nonce)
        username = "sso-user@example.com"

        monkeypatch.setattr(
            auth_api.httpx,
            "AsyncClient",
            lambda *args, **kwargs: _TokenExchangeClient({"id_token": "provider-id-token"}),
        )

        async def _fake_verify(id_token: str, authority: str, client_id: str, expected_nonce: str) -> dict:
            assert id_token == "provider-id-token"
            assert authority == settings.SSO_AUTHORITY.rstrip("/")
            assert client_id == settings.SSO_CLIENT_ID
            assert expected_nonce == nonce
            return {
                "sub": "sso-subject-123",
                "nonce": nonce,
                "email": username,
                "name": "SSO User",
                "groups": ["group-operator"],
            }

        monkeypatch.setattr(auth_api, "_verify_sso_id_token", _fake_verify)

        response = await client.get(
            "/api/auth/sso/callback",
            params={"code": "auth-code", "state": state},
            follow_redirects=False,
        )

        assert response.status_code in {302, 307}
        location = response.headers["location"]
        parsed = urlparse(location)
        params = parse_qs(parsed.query)
        assert parsed.scheme == "http"
        assert parsed.netloc == "frontend.local"
        assert parsed.path == "/login"
        assert "token" in params

        me = await client.get(
            "/api/auth/me",
            headers={"Authorization": f"Bearer {params['token'][0]}"},
        )
        assert me.status_code == 200
        me_data = me.json()
        assert me_data["identity"] == username
        assert me_data["role"] == "operator"
