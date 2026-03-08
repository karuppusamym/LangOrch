from __future__ import annotations

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from app.api.auth import _issue_jwt
from app.auth.deps import get_current_user
from app.config import settings


def _make_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/",
            "headers": [],
        }
    )


class TestGetCurrentUserAuthDisabled:
    @pytest.mark.asyncio
    async def test_returns_anon_admin_without_credentials(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_ENABLED", False)
        monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "auth-disabled-secret-with-at-least-32")

        principal = await get_current_user(_make_request(), authorization=None, x_api_key=None)

        assert principal.identity == "anonymous"
        assert principal.roles == ["admin"]

    @pytest.mark.asyncio
    async def test_accepts_valid_bearer_when_auth_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_ENABLED", False)
        monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "auth-disabled-secret-with-at-least-32")
        token = _issue_jwt("dev-user", ["operator"], 60, settings.AUTH_SECRET_KEY)

        principal = await get_current_user(
            _make_request(),
            authorization=f"Bearer {token}",
            x_api_key=None,
        )

        assert principal.identity == "dev-user"
        assert principal.roles == ["operator"]

    @pytest.mark.asyncio
    async def test_rejects_invalid_bearer_when_auth_disabled(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTH_ENABLED", False)
        monkeypatch.setattr(settings, "AUTH_SECRET_KEY", "auth-disabled-secret-with-at-least-32")

        with pytest.raises(HTTPException) as exc_info:
            await get_current_user(
                _make_request(),
                authorization="Bearer invalid-token",
                x_api_key=None,
            )

        assert exc_info.value.status_code == 401
        assert exc_info.value.detail == "Invalid or expired token"