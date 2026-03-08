from __future__ import annotations

import json

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select
from unittest.mock import AsyncMock, patch

from app.api import config as config_api
from app.config import settings
from app.db.engine import async_session
from app.db.models import SystemSetting
from app.main import app


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture(autouse=True)
async def _cleanup_system_settings():
    async with async_session() as db:
        await db.execute(delete(SystemSetting).where(SystemSetting.key.in_(["DEBUG", "METRICS_PUSH_URL"])))
        await db.commit()
    yield
    async with async_session() as db:
        await db.execute(delete(SystemSetting).where(SystemSetting.key.in_(["DEBUG", "METRICS_PUSH_URL"])))
        await db.commit()


class TestConfigApiPersistence:
    @pytest.mark.asyncio
    async def test_patch_config_persists_to_system_settings(self, client, monkeypatch):
        original_value = settings.METRICS_PUSH_URL
        try:
            monkeypatch.setattr(settings, "METRICS_PUSH_URL", None)

            response = await client.patch("/api/config", json={"metrics_push_url": "https://push.example.test"})

            assert response.status_code == 200
            assert response.json()["metrics_push_url"] == "https://push.example.test"

            async with async_session() as db:
                row = await db.get(SystemSetting, "METRICS_PUSH_URL")
                assert row is not None
                assert json.loads(row.value_json) == "https://push.example.test"
        finally:
            monkeypatch.setattr(settings, "METRICS_PUSH_URL", original_value)

    @pytest.mark.asyncio
    async def test_patch_config_reverts_settings_when_persistence_fails(self, client, monkeypatch):
        original_debug = settings.DEBUG
        try:
            monkeypatch.setattr(settings, "DEBUG", False)

            with patch.object(config_api, "_persist_config_changes", new=AsyncMock(side_effect=RuntimeError("db down"))):
                response = await client.patch("/api/config", json={"debug": True})

            assert response.status_code == 500
            assert response.json()["detail"] == "Failed to persist configuration changes"
            assert settings.DEBUG is False

            async with async_session() as db:
                row = await db.get(SystemSetting, "DEBUG")
                assert row is None
        finally:
            monkeypatch.setattr(settings, "DEBUG", original_debug)