from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_skip_bootstrap_admin_when_password_missing_in_secured_mode(monkeypatch):
    from app.services import user_service

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_ENABLED", True)
    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_USERNAME", "admin")
    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_PASSWORD", None)
    monkeypatch.setattr(user_service.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(user_service.settings, "SSO_ENABLED", False)
    monkeypatch.setattr(user_service.settings, "DEBUG", False)

    with patch("app.services.user_service.create_user", new=AsyncMock()) as create_user:
        await user_service.ensure_default_admin(db)

    create_user.assert_not_awaited()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_seed_bootstrap_admin_with_explicit_password(monkeypatch):
    from app.services import user_service

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    db = AsyncMock()
    db.execute = AsyncMock(return_value=result)
    db.commit = AsyncMock()

    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_ENABLED", True)
    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_USERNAME", "bootstrap-admin")
    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_EMAIL", "bootstrap@example.com")
    monkeypatch.setattr(user_service.settings, "BOOTSTRAP_ADMIN_PASSWORD", "StrongBootstrapPassword123!")
    monkeypatch.setattr(user_service.settings, "AUTH_ENABLED", True)
    monkeypatch.setattr(user_service.settings, "SSO_ENABLED", False)
    monkeypatch.setattr(user_service.settings, "DEBUG", False)

    with patch("app.services.user_service.create_user", new=AsyncMock()) as create_user:
        await user_service.ensure_default_admin(db)

    create_user.assert_awaited_once_with(
        db,
        username="bootstrap-admin",
        email="bootstrap@example.com",
        password="StrongBootstrapPassword123!",
        role="admin",
        full_name="Platform Administrator",
    )
    db.commit.assert_awaited_once()