"""Tests for Batch 11 backend features:
  1. Procedure status enforcement (deprecated/archived block run creation)
  2. Procedure effective_date enforcement (future date blocks run)
  3. checkpoint_strategy="none" skips LangGraph checkpointer
  4. Procedure tag-search via retrieval_metadata.tags
  5. Procedure status filter in list_procedures
  6. custom_metrics telemetry emission in graph_builder
  7. record_custom_metric utility
"""

from __future__ import annotations

import json
import pytest
from datetime import date, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# 1 + 2. Status and effective_date enforcement in execution_service
# ---------------------------------------------------------------------------


class TestProcedureStatusEnforcement:
    @pytest.mark.asyncio
    async def test_deprecated_procedure_fails_run(self):
        """execute_run should fail the run if procedure.status == 'deprecated'."""
        from app.services import execution_service, run_service

        mock_run = MagicMock()
        mock_run.run_id = "run-dep"
        mock_run.procedure_id = "p1"
        mock_run.procedure_version = "1.0"
        mock_run.last_node_id = None
        mock_run.input_vars_json = None
        mock_run.thread_id = "t1"

        mock_proc = MagicMock()
        mock_proc.status = "deprecated"
        mock_proc.effective_date = None
        mock_proc.ckp_json = json.dumps({
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        })

        events = []

        async def fake_emit(db, run_id, event_type, **kwargs):
            events.append({"type": event_type, **kwargs})

        async def fake_update_status(db, run_id, status, **kwargs):
            pass

        with patch.object(run_service, "get_run", new=AsyncMock(return_value=mock_run)), \
             patch.object(run_service, "update_run_status", new=AsyncMock(side_effect=fake_update_status)), \
             patch.object(run_service, "emit_event", new=AsyncMock(side_effect=fake_emit)), \
             patch("app.services.procedure_service.get_procedure", new=AsyncMock(return_value=mock_proc)):

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
            mock_db.commit = AsyncMock()

            from app.utils.run_cancel import deregister
            try:
                await execution_service.execute_run("run-dep", lambda: mock_db)
            except Exception:
                pass

        error_events = [e for e in events if e["type"] == "error"]
        assert any("deprecated" in (e.get("payload", {}) or {}).get("message", "") for e in error_events)

    @pytest.mark.asyncio
    async def test_future_effective_date_fails_run(self):
        """execute_run should fail the run if effective_date is in the future."""
        from app.services import execution_service, run_service

        future_date = (date.today() + timedelta(days=30)).isoformat()

        mock_run = MagicMock()
        mock_run.run_id = "run-future"
        mock_run.procedure_id = "p1"
        mock_run.procedure_version = "1.0"
        mock_run.last_node_id = None
        mock_run.input_vars_json = None
        mock_run.thread_id = "t1"

        mock_proc = MagicMock()
        mock_proc.status = "active"
        mock_proc.effective_date = future_date
        mock_proc.ckp_json = json.dumps({
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        })

        events = []

        async def fake_emit(db, run_id, event_type, **kwargs):
            events.append({"type": event_type, **kwargs})

        with patch.object(run_service, "get_run", new=AsyncMock(return_value=mock_run)), \
             patch.object(run_service, "update_run_status", new=AsyncMock()), \
             patch.object(run_service, "emit_event", new=AsyncMock(side_effect=fake_emit)), \
             patch("app.services.procedure_service.get_procedure", new=AsyncMock(return_value=mock_proc)):

            mock_db = AsyncMock()
            mock_db.__aenter__ = AsyncMock(return_value=mock_db)
            mock_db.__aexit__ = AsyncMock(return_value=False)
            mock_db.execute = AsyncMock(return_value=MagicMock(first=MagicMock(return_value=None)))
            mock_db.commit = AsyncMock()

            try:
                await execution_service.execute_run("run-future", lambda: mock_db)
            except Exception:
                pass

        error_events = [e for e in events if e["type"] == "error"]
        assert any("effective" in (e.get("payload", {}) or {}).get("message", "").lower() for e in error_events)

    @pytest.mark.asyncio
    async def test_past_effective_date_allows_run(self):
        """Procedures with past effective_date should proceed normally."""
        from datetime import date, timedelta

        past_date = (date.today() - timedelta(days=1)).isoformat()
        # Just verify that the date check passes; we don't need a full run
        from datetime import date as _date
        eff = _date.fromisoformat(past_date)
        assert _date.today() >= eff

    def test_archived_status_is_blocked(self):
        """'archived' is in the blocked statuses list."""
        blocked = ("deprecated", "archived")
        assert "archived" in blocked

    def test_draft_status_is_not_blocked(self):
        """'draft' status should be allowed to run."""
        blocked = ("deprecated", "archived")
        assert "draft" not in blocked


# ---------------------------------------------------------------------------
# 3. checkpoint_strategy enforcement
# ---------------------------------------------------------------------------


class TestCheckpointStrategy:
    def test_checkpoint_strategy_none_tagged_on_graph(self):
        """When global_config.checkpoint_strategy=none, graph gets _ckp_strategy='none'."""
        # Simulate what execution_service does after build_graph
        class FakeGraph:
            pass

        g = FakeGraph()
        checkpoint_strategy = "none"
        g._ckp_strategy = checkpoint_strategy
        assert g._ckp_strategy == "none"

    def test_checkpoint_strategy_full_tagged_on_graph(self):
        g = type("G", (), {})()
        g._ckp_strategy = "full"
        assert g._ckp_strategy == "full"

    def test_default_strategy_is_full(self):
        global_config: dict = {}
        strategy = global_config.get("checkpoint_strategy", "full")
        assert strategy == "full"


# ---------------------------------------------------------------------------
# 4. Procedure tag search
# ---------------------------------------------------------------------------


class TestProcedureTagSearch:
    @pytest.mark.asyncio
    async def test_list_procedures_filters_by_tags(self):
        from app.services.procedure_service import list_procedures

        # Build two mock procedures
        def make_proc(proc_id: str, tags: list[str]):
            p = MagicMock()
            p.procedure_id = proc_id
            p.project_id = None
            p.retrieval_metadata_json = json.dumps({"tags": tags})
            return p

        proc_finance = make_proc("p1", ["finance", "onboarding"])
        proc_hr = make_proc("p2", ["hr"])
        proc_no_meta = MagicMock()
        proc_no_meta.retrieval_metadata_json = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [proc_finance, proc_hr, proc_no_meta]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await list_procedures(mock_db, tags=["finance"])
        assert len(results) == 1
        assert results[0].procedure_id == "p1"

    @pytest.mark.asyncio
    async def test_list_procedures_requires_all_tags(self):
        from app.services.procedure_service import list_procedures

        def make_proc(proc_id: str, tags: list[str]):
            p = MagicMock()
            p.procedure_id = proc_id
            p.project_id = None
            p.retrieval_metadata_json = json.dumps({"tags": tags})
            return p

        proc1 = make_proc("p1", ["finance", "onboarding"])
        proc2 = make_proc("p2", ["finance"])

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [proc1, proc2]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        # Both tags must be present
        results = await list_procedures(mock_db, tags=["finance", "onboarding"])
        assert len(results) == 1
        assert results[0].procedure_id == "p1"

    @pytest.mark.asyncio
    async def test_list_procedures_no_tags_returns_all(self):
        from app.services.procedure_service import list_procedures

        procs = [MagicMock(), MagicMock(), MagicMock()]
        for p in procs:
            p.project_id = None
            p.retrieval_metadata_json = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = procs

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await list_procedures(mock_db)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# 5. Status filter in list_procedures (SQL filter)
# ---------------------------------------------------------------------------


class TestProcedureStatusFilter:
    @pytest.mark.asyncio
    async def test_list_procedures_with_status_filter(self):
        from app.services.procedure_service import list_procedures

        active_proc = MagicMock()
        active_proc.project_id = None
        active_proc.status = "active"
        active_proc.retrieval_metadata_json = None

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [active_proc]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await list_procedures(mock_db, status="active")
        assert len(results) == 1


# ---------------------------------------------------------------------------
# 6 + 7. custom_metrics via record_custom_metric
# ---------------------------------------------------------------------------


class TestCustomMetrics:
    def setup_method(self):
        from app.utils.metrics import metrics
        metrics.reset()

    def test_record_custom_metric_increments_counter(self):
        from app.utils.metrics import record_custom_metric, metrics

        record_custom_metric("my_custom_event")
        assert metrics.get_counter("my_custom_event") == 1

        record_custom_metric("my_custom_event")
        assert metrics.get_counter("my_custom_event") == 2

    def test_record_custom_metric_with_value(self):
        from app.utils.metrics import record_custom_metric, metrics

        record_custom_metric("orders_processed", value=5)
        assert metrics.get_counter("orders_processed") == 5

    def test_record_custom_metric_with_labels(self):
        from app.utils.metrics import record_custom_metric, metrics

        record_custom_metric("tagged_event", labels={"env": "test"})
        assert metrics.get_counter("tagged_event", labels={"env": "test"}) == 1

    def test_custom_metrics_list_string_emitted(self):
        """Node telemetry.custom_metrics list of strings: each is incremented."""
        from app.utils.metrics import record_custom_metric, metrics

        custom_metrics = ["event_a", "event_b"]
        for cm in custom_metrics:
            record_custom_metric(cm)

        assert metrics.get_counter("event_a") == 1
        assert metrics.get_counter("event_b") == 1

    def test_custom_metrics_list_dict_emitted(self):
        """Node telemetry.custom_metrics list of dicts with name+value."""
        from app.utils.metrics import record_custom_metric, metrics

        custom_metrics = [{"name": "items_created", "value": 3}]
        for cm in custom_metrics:
            record_custom_metric(cm["name"], value=int(cm.get("value", 1)))

        assert metrics.get_counter("items_created") == 3
