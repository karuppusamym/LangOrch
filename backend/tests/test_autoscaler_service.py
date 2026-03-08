from __future__ import annotations

import json

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.config import settings
from app.db.engine import async_session
from app.db.models import AgentInstance, Procedure, Run, RunJob
from app.services import autoscaler_service


class _WebhookResponse:
    def __init__(self, status_code: int = 200):
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _WebhookClient:
    def __init__(self, response: _WebhookResponse, calls: list[dict]):
        self._response = response
        self._calls = calls

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def post(self, url: str, json: dict, headers: dict):
        self._calls.append({"url": url, "json": json, "headers": headers})
        return self._response


class TestRequestPoolScaleAction:
    @pytest.mark.asyncio
    async def test_returns_true_when_webhook_not_configured(self, monkeypatch):
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_URL", None)

        ok = await autoscaler_service.request_pool_scale_action("pool-a", 3, "scale up")

        assert ok is True

    @pytest.mark.asyncio
    async def test_posts_to_configured_webhook(self, monkeypatch):
        calls: list[dict] = []
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_URL", "https://scale.example.test/hooks/autoscaler")
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_TOKEN", "secret-token")
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_TIMEOUT_SECONDS", 7.5)
        monkeypatch.setattr(
            autoscaler_service.httpx,
            "AsyncClient",
            lambda timeout: _WebhookClient(_WebhookResponse(202), calls),
        )

        ok = await autoscaler_service.request_pool_scale_action("pool-b", 5, "queue depth high")

        assert ok is True
        assert len(calls) == 1
        assert calls[0]["url"] == "https://scale.example.test/hooks/autoscaler"
        assert calls[0]["json"]["pool_id"] == "pool-b"
        assert calls[0]["json"]["target_instances"] == 5
        assert calls[0]["json"]["reason"] == "queue depth high"
        assert calls[0]["headers"]["Authorization"] == "Bearer secret-token"

    @pytest.mark.asyncio
    async def test_returns_false_when_webhook_fails(self, monkeypatch, caplog):
        calls: list[dict] = []
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_URL", "https://scale.example.test/hooks/autoscaler")
        monkeypatch.setattr(settings, "AUTOSCALER_SCALE_WEBHOOK_TOKEN", None)
        monkeypatch.setattr(
            autoscaler_service.httpx,
            "AsyncClient",
            lambda timeout: _WebhookClient(_WebhookResponse(500), calls),
        )
        caplog.set_level("WARNING")

        ok = await autoscaler_service.request_pool_scale_action("pool-c", 2, "scale down")

        assert ok is False
        assert len(calls) == 1
        assert "Autoscaler scale action failed for pool pool-c" in caplog.text


@pytest_asyncio.fixture
async def autoscaler_db_session():
    async with async_session() as db:
        await db.execute(delete(RunJob))
        await db.execute(delete(Run))
        await db.execute(delete(Procedure))
        await db.execute(delete(AgentInstance))
        await db.commit()
        try:
            yield db
        finally:
            await db.execute(delete(RunJob))
            await db.execute(delete(Run))
            await db.execute(delete(Procedure))
            await db.execute(delete(AgentInstance))
            await db.commit()


class TestQueueDepthByPool:
    @pytest.mark.asyncio
    async def test_counts_queued_runs_for_unique_channel_pool(self, autoscaler_db_session):
        db = autoscaler_db_session
        db.add(
            AgentInstance(
                agent_id="agent-web-1",
                name="Web Agent",
                channel="web",
                base_url="http://agent-web-1",
                resource_key="web-key",
                pool_id="web_pool",
                status="online",
            )
        )
        db.add(
            Procedure(
                procedure_id="proc-web",
                version="1.0.0",
                status="active",
                name="Web Procedure",
                ckp_json=json.dumps(
                    {
                        "procedure_id": "proc-web",
                        "version": "1.0.0",
                        "workflow_graph": {
                            "start_node": "start",
                            "nodes": {
                                "start": {
                                    "type": "sequence",
                                    "agent": "WEB",
                                    "steps": [],
                                }
                            },
                        },
                    }
                ),
            )
        )
        run = Run(
            run_id="run-web-1",
            procedure_id="proc-web",
            procedure_version="1.0.0",
            thread_id="thread-web-1",
            status="created",
        )
        db.add(run)
        db.add(RunJob(run_id=run.run_id, status="queued"))
        await db.commit()

        queue_depth = await autoscaler_service.get_queue_depth_by_pool(db)

        assert queue_depth == {"web_pool": 1}

    @pytest.mark.asyncio
    async def test_skips_ambiguous_channel_with_multiple_pools(self, autoscaler_db_session):
        db = autoscaler_db_session
        db.add_all(
            [
                AgentInstance(
                    agent_id="agent-web-1",
                    name="Web Agent 1",
                    channel="web",
                    base_url="http://agent-web-1",
                    resource_key="web-key-1",
                    pool_id="web_pool_a",
                    status="online",
                ),
                AgentInstance(
                    agent_id="agent-web-2",
                    name="Web Agent 2",
                    channel="web",
                    base_url="http://agent-web-2",
                    resource_key="web-key-2",
                    pool_id="web_pool_b",
                    status="online",
                ),
            ]
        )
        db.add(
            Procedure(
                procedure_id="proc-web-ambiguous",
                version="1.0.0",
                status="active",
                name="Web Procedure Ambiguous",
                ckp_json=json.dumps(
                    {
                        "procedure_id": "proc-web-ambiguous",
                        "version": "1.0.0",
                        "workflow_graph": {
                            "start_node": "start",
                            "nodes": {
                                "start": {
                                    "type": "sequence",
                                    "agent": "web",
                                    "steps": [],
                                }
                            },
                        },
                    }
                ),
            )
        )
        run = Run(
            run_id="run-web-ambiguous",
            procedure_id="proc-web-ambiguous",
            procedure_version="1.0.0",
            thread_id="thread-web-ambiguous",
            status="created",
        )
        db.add(run)
        db.add(RunJob(run_id=run.run_id, status="queued"))
        await db.commit()

        queue_depth = await autoscaler_service.get_queue_depth_by_pool(db)

        assert queue_depth == {}

    @pytest.mark.asyncio
    async def test_evaluate_autoscaling_decision_uses_inferred_queue_depth(self, autoscaler_db_session):
        db = autoscaler_db_session
        db.add(
            AgentInstance(
                agent_id="agent-db-1",
                name="DB Agent",
                channel="database",
                base_url="http://agent-db-1",
                resource_key="db-key",
                pool_id="db_pool",
                status="online",
            )
        )
        db.add(
            Procedure(
                procedure_id="proc-db",
                version="1.0.0",
                status="active",
                name="DB Procedure",
                ckp_json=json.dumps(
                    {
                        "procedure_id": "proc-db",
                        "version": "1.0.0",
                        "workflow_graph": {
                            "start_node": "start",
                            "nodes": {
                                "start": {
                                    "type": "sequence",
                                    "agent": "DATABASE",
                                    "steps": [],
                                }
                            },
                        },
                    }
                ),
            )
        )
        run = Run(
            run_id="run-db-1",
            procedure_id="proc-db",
            procedure_version="1.0.0",
            thread_id="thread-db-1",
            status="created",
        )
        db.add(run)
        db.add(RunJob(run_id=run.run_id, status="queued"))
        await db.commit()

        decision, target, reason = await autoscaler_service.evaluate_autoscaling_decision(
            db,
            pool_id="db_pool",
            current_instances=1,
            policy={
                **autoscaler_service.DEFAULT_POLICY,
                "queue_depth_threshold": 1,
                "saturation_threshold": 999,
                "max_instances": 5,
            },
        )

        assert decision == "scale_up"
        assert target == 2
        assert "queue depth: 1" in reason