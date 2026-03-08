"""Release governance API regression tests."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import app


def _uid() -> str:
    """Return a short unique suffix for test isolation."""
    return uuid.uuid4().hex[:8]


@pytest.fixture
async def client():
    """Create an async test client for the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


class TestProcedureReleaseGovernanceAPI:
    @pytest.mark.asyncio
    async def test_promote_procedure_to_qa_sets_release_metadata_and_audit(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import AuditEvent, Procedure

        async with async_session() as db:
            await db.execute(delete(AuditEvent))
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"release_test_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "name": "Release Ready",
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "release"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }

        import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
        assert import_resp.status_code == 201

        promote_resp = await client.post(
            f"/api/procedures/{pid}/1.0.0/promote",
            json={"target_channel": "qa"},
        )
        assert promote_resp.status_code == 200
        promoted_payload = promote_resp.json()
        assert promoted_payload["promoted"]["release_channel"] == "qa"
        assert promoted_payload["promoted"]["status"] == "active"
        assert promoted_payload["promoted"]["promoted_by"] == "anonymous"
        assert promoted_payload["previous_channel_version"] is None

        audit_resp = await client.get("/api/audit?category=procedure_release&action=promote")
        assert audit_resp.status_code == 200
        assert any(
            (event.get("meta") or {}).get("procedure_id") == pid
            and (event.get("meta") or {}).get("target_channel") == "qa"
            for event in audit_resp.json()["events"]
        )

    @pytest.mark.asyncio
    async def test_promote_procedure_to_prod_tracks_previous_version_for_rollback(self, client):
        from sqlalchemy import delete, select

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_test_{_uid()}"
        for version in ["1.0.0", "1.1.0"]:
            ckp = {
                "procedure_id": pid,
                "version": version,
                "name": f"Rollback {version}",
                "global_config": {},
                "variables_schema": {},
                "workflow_graph": {
                    "start_node": "start",
                    "nodes": {
                        "start": {
                            "type": "sequence",
                            "next_node": "end",
                            "steps": [{"step_id": "s1", "action": "log", "message": version}],
                        },
                        "end": {"type": "terminate", "status": "success"},
                    },
                },
            }
            import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
            assert import_resp.status_code == 201

        first_promote = await client.post(
            f"/api/procedures/{pid}/1.0.0/promote",
            json={"target_channel": "prod"},
        )
        assert first_promote.status_code == 200
        assert first_promote.json()["previous_channel_version"] is None

        second_promote = await client.post(
            f"/api/procedures/{pid}/1.1.0/promote",
            json={"target_channel": "prod"},
        )
        assert second_promote.status_code == 200
        payload = second_promote.json()
        assert payload["previous_channel_version"] == "1.0.0"
        assert payload["promoted"]["promoted_from_version"] == "1.0.0"

        async with async_session() as db:
            old_version = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.procedure_id == pid,
                        Procedure.version == "1.0.0",
                    )
                )
            ).scalars().first()
        assert old_version is not None
        assert old_version.status == "deprecated"

    @pytest.mark.asyncio
    async def test_promote_procedure_rejects_backward_channel_transition(self, client):
        pid = f"release_invalid_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "2.0.0",
            "name": "Invalid Transition",
            "release": {"channel": "qa"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "invalid"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
        assert import_resp.status_code == 201

        resp = await client.post(
            f"/api/procedures/{pid}/2.0.0/promote",
            json={"target_channel": "dev"},
        )
        assert resp.status_code == 422
        assert "Cannot promote" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_restores_previous_version_and_emits_audit(self, client):
        from sqlalchemy import delete, select

        from app.db.engine import async_session
        from app.db.models import AuditEvent, Procedure

        async with async_session() as db:
            await db.execute(delete(AuditEvent))
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_api_{_uid()}"
        for version in ["1.0.0", "1.1.0"]:
            ckp = {
                "procedure_id": pid,
                "version": version,
                "name": f"Rollback API {version}",
                "global_config": {},
                "variables_schema": {},
                "workflow_graph": {
                    "start_node": "start",
                    "nodes": {
                        "start": {
                            "type": "sequence",
                            "next_node": "end",
                            "steps": [{"step_id": "s1", "action": "log", "message": version}],
                        },
                        "end": {"type": "terminate", "status": "success"},
                    },
                },
            }
            import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
            assert import_resp.status_code == 201

        promote_v1 = await client.post(
            f"/api/procedures/{pid}/1.0.0/promote",
            json={"target_channel": "prod"},
        )
        assert promote_v1.status_code == 200

        promote_v11 = await client.post(
            f"/api/procedures/{pid}/1.1.0/promote",
            json={"target_channel": "prod"},
        )
        assert promote_v11.status_code == 200

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod"},
        )
        assert rollback_resp.status_code == 200
        payload = rollback_resp.json()
        assert payload["replaced_version"] == "1.1.0"
        assert payload["restored"]["version"] == "1.0.0"
        assert payload["restored"]["release_channel"] == "prod"
        assert payload["restored"]["promoted_from_version"] == "1.1.0"

        async with async_session() as db:
            restored = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.procedure_id == pid,
                        Procedure.version == "1.0.0",
                    )
                )
            ).scalars().first()
            replaced = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.procedure_id == pid,
                        Procedure.version == "1.1.0",
                    )
                )
            ).scalars().first()
        assert restored is not None
        assert replaced is not None
        assert restored.status == "active"
        assert replaced.status == "deprecated"

        audit_resp = await client.get("/api/audit?category=procedure_release&action=rollback")
        assert audit_resp.status_code == 200
        assert any(
            (event.get("meta") or {}).get("procedure_id") == pid
            and (event.get("meta") or {}).get("from_version") == "1.1.0"
            and (event.get("meta") or {}).get("restored_version") == "1.0.0"
            for event in audit_resp.json()["events"]
        )

    @pytest.mark.asyncio
    async def test_rollback_procedure_requires_resolvable_target_version(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_missing_{_uid()}"
        ckp = {
            "procedure_id": pid,
            "version": "2.0.0",
            "name": "Rollback Missing",
            "status": "active",
            "release": {"channel": "prod"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "missing"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
        assert import_resp.status_code == 201

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/2.0.0/rollback",
            json={"target_channel": "prod"},
        )
        assert rollback_resp.status_code == 422
        assert "rollback_to_version is required" in rollback_resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_rejects_target_version_in_different_channel(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_channel_{_uid()}"
        for version in ["1.0.0", "1.1.0"]:
            ckp = {
                "procedure_id": pid,
                "version": version,
                "name": f"Rollback Channel {version}",
                "global_config": {},
                "variables_schema": {},
                "workflow_graph": {
                    "start_node": "start",
                    "nodes": {
                        "start": {
                            "type": "sequence",
                            "next_node": "end",
                            "steps": [{"step_id": "s1", "action": "log", "message": version}],
                        },
                        "end": {"type": "terminate", "status": "success"},
                    },
                },
            }
            import_resp = await client.post("/api/procedures", json={"ckp_json": ckp})
            assert import_resp.status_code == 201

        promote_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/promote",
            json={"target_channel": "prod"},
        )
        assert promote_resp.status_code == 200

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod", "rollback_to_version": "1.0.0"},
        )
        assert rollback_resp.status_code == 422
        assert "not prod" in rollback_resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_requires_current_version_active(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_active_{_uid()}"
        archived_candidate_ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "name": "Rollback Candidate",
            "status": "active",
            "release": {"channel": "prod"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "candidate"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        current_not_active_ckp = {
            "procedure_id": pid,
            "version": "1.1.0",
            "name": "Rollback Source",
            "status": "deprecated",
            "release": {"channel": "prod", "promoted_from_version": "1.0.0"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "source"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }

        resp_v1 = await client.post("/api/procedures", json={"ckp_json": archived_candidate_ckp})
        assert resp_v1.status_code == 201
        resp_v11 = await client.post("/api/procedures", json={"ckp_json": current_not_active_ckp})
        assert resp_v11.status_code == 201

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod", "rollback_to_version": "1.0.0"},
        )
        assert rollback_resp.status_code == 422
        assert "active version" in rollback_resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_rejects_archived_target_version(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_archived_{_uid()}"
        archived_target_ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "name": "Archived Target",
            "status": "archived",
            "release": {"channel": "prod"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "archived"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        current_active_ckp = {
            "procedure_id": pid,
            "version": "1.1.0",
            "name": "Current Active",
            "status": "active",
            "release": {"channel": "prod", "promoted_from_version": "1.0.0"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "active"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }

        resp_v1 = await client.post("/api/procedures", json={"ckp_json": archived_target_ckp})
        assert resp_v1.status_code == 201
        resp_v11 = await client.post("/api/procedures", json={"ckp_json": current_active_ckp})
        assert resp_v11.status_code == 201

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod", "rollback_to_version": "1.0.0"},
        )
        assert rollback_resp.status_code == 422
        assert "archived" in rollback_resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_rejects_draft_target_version(self, client):
        from sqlalchemy import delete

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_draft_{_uid()}"
        draft_target_ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "name": "Draft Target",
            "status": "draft",
            "release": {"channel": "prod"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "draft"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        current_active_ckp = {
            "procedure_id": pid,
            "version": "1.1.0",
            "name": "Current Active",
            "status": "active",
            "release": {"channel": "prod", "promoted_from_version": "1.0.0"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "active"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }

        resp_v1 = await client.post("/api/procedures", json={"ckp_json": draft_target_ckp})
        assert resp_v1.status_code == 201
        resp_v11 = await client.post("/api/procedures", json={"ckp_json": current_active_ckp})
        assert resp_v11.status_code == 201

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod", "rollback_to_version": "1.0.0"},
        )
        assert rollback_resp.status_code == 422
        assert "draft" in rollback_resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_rollback_procedure_allows_same_channel_deprecated_target(self, client):
        from sqlalchemy import delete, select

        from app.db.engine import async_session
        from app.db.models import Procedure

        async with async_session() as db:
            await db.execute(delete(Procedure))
            await db.commit()

        pid = f"rollback_deprecated_{_uid()}"
        target_deprecated_ckp = {
            "procedure_id": pid,
            "version": "1.0.0",
            "name": "Deprecated Target",
            "status": "deprecated",
            "release": {"channel": "prod"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "target"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }
        current_active_ckp = {
            "procedure_id": pid,
            "version": "1.1.0",
            "name": "Current Active",
            "status": "active",
            "release": {"channel": "prod", "promoted_from_version": "1.0.0"},
            "global_config": {},
            "variables_schema": {},
            "workflow_graph": {
                "start_node": "start",
                "nodes": {
                    "start": {
                        "type": "sequence",
                        "next_node": "end",
                        "steps": [{"step_id": "s1", "action": "log", "message": "current"}],
                    },
                    "end": {"type": "terminate", "status": "success"},
                },
            },
        }

        resp_v1 = await client.post("/api/procedures", json={"ckp_json": target_deprecated_ckp})
        assert resp_v1.status_code == 201
        resp_v11 = await client.post("/api/procedures", json={"ckp_json": current_active_ckp})
        assert resp_v11.status_code == 201

        rollback_resp = await client.post(
            f"/api/procedures/{pid}/1.1.0/rollback",
            json={"target_channel": "prod", "rollback_to_version": "1.0.0"},
        )
        assert rollback_resp.status_code == 200
        payload = rollback_resp.json()
        assert payload["replaced_version"] == "1.1.0"
        assert payload["restored"]["version"] == "1.0.0"
        assert payload["restored"]["status"] == "active"

        async with async_session() as db:
            restored = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.procedure_id == pid,
                        Procedure.version == "1.0.0",
                    )
                )
            ).scalars().first()
            replaced = (
                await db.execute(
                    select(Procedure).where(
                        Procedure.procedure_id == pid,
                        Procedure.version == "1.1.0",
                    )
                )
            ).scalars().first()

        assert restored is not None and restored.status == "active"
        assert replaced is not None and replaced.status == "deprecated"
