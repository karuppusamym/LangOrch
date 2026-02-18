"""Tests for Batch 12 backend features:
  1. AgentInstanceOut.capabilities parsed from comma-Sep string
  2. AgentInstanceUpdate schema validation
  3. Projects service CRUD (list/get/create/update/delete)
  4. Projects API router responses
  5. Agents API PUT /{agent_id} update capabilities/status
  6. Agents API DELETE /{agent_id} returns 204
"""

from __future__ import annotations

import datetime
import pytest
from unittest.mock import MagicMock, AsyncMock, patch


# ---------------------------------------------------------------------------
# 1. AgentInstanceOut capabilities parsing
# ---------------------------------------------------------------------------


class TestAgentInstanceOutCapabilities:
    def test_capabilities_from_comma_sep_string(self):
        from app.schemas.agents import AgentInstanceOut

        obj = AgentInstanceOut.model_validate({
            "agent_id": "a1",
            "name": "Test",
            "channel": "web",
            "base_url": "http://localhost:9000",
            "resource_key": "web_default",
            "status": "online",
            "concurrency_limit": 1,
            "capabilities": "click,type,scroll",
            "registered_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        assert obj.capabilities == ["click", "type", "scroll"]

    def test_capabilities_from_list(self):
        from app.schemas.agents import AgentInstanceOut

        obj = AgentInstanceOut.model_validate({
            "agent_id": "a2",
            "name": "Test",
            "channel": "web",
            "base_url": "http://localhost:9000",
            "resource_key": "web_default",
            "status": "online",
            "concurrency_limit": 1,
            "capabilities": ["click", "type"],
            "registered_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        assert obj.capabilities == ["click", "type"]

    def test_capabilities_none_returns_empty_list(self):
        from app.schemas.agents import AgentInstanceOut

        obj = AgentInstanceOut.model_validate({
            "agent_id": "a3",
            "name": "Test",
            "channel": "web",
            "base_url": "http://localhost:9000",
            "resource_key": "web_default",
            "status": "online",
            "concurrency_limit": 1,
            "capabilities": None,
            "registered_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        assert obj.capabilities == []

    def test_capabilities_empty_string_returns_empty_list(self):
        from app.schemas.agents import AgentInstanceOut

        obj = AgentInstanceOut.model_validate({
            "agent_id": "a4",
            "name": "Test",
            "channel": "web",
            "base_url": "http://localhost:9000",
            "resource_key": "web_default",
            "status": "online",
            "concurrency_limit": 1,
            "capabilities": "",
            "registered_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        assert obj.capabilities == []

    def test_capabilities_whitespace_trimmed(self):
        from app.schemas.agents import AgentInstanceOut

        obj = AgentInstanceOut.model_validate({
            "agent_id": "a5",
            "name": "Test",
            "channel": "web",
            "base_url": "http://localhost:9000",
            "resource_key": "web_default",
            "status": "online",
            "concurrency_limit": 1,
            "capabilities": " click , type , scroll ",
            "registered_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-01T00:00:00",
        })
        assert obj.capabilities == ["click", "type", "scroll"]


# ---------------------------------------------------------------------------
# 2. AgentInstanceUpdate validation
# ---------------------------------------------------------------------------


class TestAgentInstanceUpdate:
    def test_all_fields_optional(self):
        from app.schemas.agents import AgentInstanceUpdate

        upd = AgentInstanceUpdate()
        assert upd.status is None
        assert upd.base_url is None
        assert upd.concurrency_limit is None
        assert upd.capabilities is None

    def test_partial_update(self):
        from app.schemas.agents import AgentInstanceUpdate

        upd = AgentInstanceUpdate(status="offline", concurrency_limit=3)
        assert upd.status == "offline"
        assert upd.concurrency_limit == 3
        assert upd.base_url is None

    def test_capabilities_as_list(self):
        from app.schemas.agents import AgentInstanceUpdate

        upd = AgentInstanceUpdate(capabilities=["click", "type"])
        assert upd.capabilities == ["click", "type"]


# ---------------------------------------------------------------------------
# 3. Projects schemas
# ---------------------------------------------------------------------------


class TestProjectSchemas:
    def test_project_create_valid(self):
        from app.schemas.projects import ProjectCreate

        p = ProjectCreate(name="My Project", description="Desc")
        assert p.name == "My Project"
        assert p.description == "Desc"

    def test_project_create_description_optional(self):
        from app.schemas.projects import ProjectCreate

        p = ProjectCreate(name="Minimal")
        assert p.description is None

    def test_project_update_all_optional(self):
        from app.schemas.projects import ProjectUpdate

        p = ProjectUpdate()
        assert p.name is None
        assert p.description is None

    def test_project_update_partial(self):
        from app.schemas.projects import ProjectUpdate

        p = ProjectUpdate(name="Renamed")
        assert p.name == "Renamed"
        assert p.description is None


# ---------------------------------------------------------------------------
# 4. Projects service functions (async)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectService:
    async def test_list_projects(self):
        from app.services import project_service

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await project_service.list_projects(mock_db)
        assert result == []

    async def test_get_project_not_found(self):
        from app.services import project_service

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await project_service.get_project(mock_db, "nonexistent")
        assert result is None

    async def test_create_project(self):
        from app.services import project_service
        from app.db.models import Project

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await project_service.create_project(mock_db, "Test", "Desc")
        mock_db.add.assert_called_once()
        mock_db.flush.assert_awaited_once()

    async def test_delete_project_not_found(self):
        from app.services import project_service

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await project_service.delete_project(mock_db, "nope")
        assert result is False

    async def test_delete_project_found(self):
        from app.services import project_service
        from app.db.models import Project

        mock_db = AsyncMock()
        mock_proj = MagicMock(spec=Project)
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_proj
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.delete = AsyncMock()
        mock_db.flush = AsyncMock()

        result = await project_service.delete_project(mock_db, "proj-1")
        assert result is True
        mock_db.delete.assert_awaited_once_with(mock_proj)

    async def test_update_project_not_found(self):
        from app.services import project_service

        mock_db = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=mock_result)

        result = await project_service.update_project(mock_db, "nope", name="New")
        assert result is None

    async def test_update_project_changes_name(self):
        from app.services import project_service
        from app.db.models import Project

        mock_db = AsyncMock()
        mock_proj = MagicMock(spec=Project)
        mock_proj.name = "Old"
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = mock_proj
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        result = await project_service.update_project(mock_db, "proj-1", name="New")
        assert mock_proj.name == "New"


# ---------------------------------------------------------------------------
# 5 + 6. Projects API — mock service + test router HTTP behaviour
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestProjectsAPI:
    def _make_app(self):
        from fastapi import FastAPI
        from app.api.projects import router
        from app.db.engine import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/projects")

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        return app

    async def test_list_projects_returns_200(self):
        import httpx
        from httpx import ASGITransport

        app = self._make_app()
        with patch("app.services.project_service.list_projects", new=AsyncMock(return_value=[])):
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_project_not_found_returns_404(self):
        import httpx
        from httpx import ASGITransport

        app = self._make_app()
        with patch("app.services.project_service.get_project", new=AsyncMock(return_value=None)):
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.get("/api/projects/nonexistent")
        assert resp.status_code == 404

    async def test_delete_project_not_found_returns_404(self):
        import httpx
        from httpx import ASGITransport

        app = self._make_app()
        with patch("app.services.project_service.delete_project", new=AsyncMock(return_value=False)):
            async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
                resp = await client.delete("/api/projects/nonexistent")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 7. Agents PUT + DELETE API
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestAgentsUpdateDeleteAPI:
    def _make_app(self):
        from fastapi import FastAPI
        from app.api.agents import router
        from app.db.engine import get_db

        app = FastAPI()
        app.include_router(router, prefix="/api/agents")

        async def override_db():
            yield AsyncMock()

        app.dependency_overrides[get_db] = override_db
        return app

    async def test_put_agent_not_found_returns_404(self):
        import httpx
        from httpx import ASGITransport

        app = self._make_app()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _fake_execute(*args, **kwargs):
            return mock_result

        async def db_override():
            db = AsyncMock()
            db.execute = AsyncMock(side_effect=_fake_execute)
            yield db

        from app.db.engine import get_db
        app.dependency_overrides[get_db] = db_override

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.put("/api/agents/nonexistent", json={"status": "offline"})
        assert resp.status_code == 404

    async def test_delete_agent_not_found_returns_404(self):
        import httpx
        from httpx import ASGITransport

        app = self._make_app()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None

        async def _fake_execute(*args, **kwargs):
            return mock_result

        async def db_override():
            db = AsyncMock()
            db.execute = AsyncMock(side_effect=_fake_execute)
            yield db

        from app.db.engine import get_db
        app.dependency_overrides[get_db] = db_override

        async with httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.delete("/api/agents/nonexistent")
        assert resp.status_code == 404

