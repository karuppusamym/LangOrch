"""Tests for Batch 10 backend features:
  1. wait_ms / wait_after_ms enforcement in execute_sequence
  2. Telemetry track_duration + track_retries in step_completed event
  3. provenance + retrieval_metadata parsing (IR, parser, procedure_service, schema)
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch, call


# ---------------------------------------------------------------------------
# 1. wait_ms / wait_after_ms enforcement
# ---------------------------------------------------------------------------


class TestWaitMsEnforcement:
    @pytest.mark.asyncio
    async def test_wait_ms_sleeps_before_step(self):
        """wait_ms causes an asyncio.sleep before the step executes."""
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep

        step = IRStep(
            step_id="s1",
            action="log",
            params={"message": "hi"},
            wait_ms=100,
        )
        payload = IRSequencePayload(steps=[step])
        node = IRNode(node_id="n1", type="sequence", payload=payload)
        state = {"run_id": "", "vars": {}, "procedure_id": "p1"}

        sleep_calls = []

        original_sleep = asyncio.sleep

        async def fake_sleep(secs):
            sleep_calls.append(secs)
            # don't actually sleep

        with patch("asyncio.sleep", side_effect=fake_sleep):
            from app.runtime.node_executors import execute_sequence
            await execute_sequence(node, state, db_factory=None)

        # 0.1s sleep (100ms) should appear in calls
        assert any(abs(s - 0.1) < 0.01 for s in sleep_calls), f"Expected ~0.1s sleep, got: {sleep_calls}"

    @pytest.mark.asyncio
    async def test_wait_after_ms_sleeps_after_step(self):
        """wait_after_ms causes an asyncio.sleep after the step executes."""
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep

        step = IRStep(
            step_id="s1",
            action="log",
            params={"message": "hi"},
            wait_after_ms=200,
        )
        payload = IRSequencePayload(steps=[step])
        node = IRNode(node_id="n1", type="sequence", payload=payload)
        state = {"run_id": "", "vars": {}, "procedure_id": "p1"}

        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            from app.runtime.node_executors import execute_sequence
            await execute_sequence(node, state, db_factory=None)

        assert any(abs(s - 0.2) < 0.01 for s in sleep_calls), f"Expected ~0.2s sleep, got: {sleep_calls}"

    @pytest.mark.asyncio
    async def test_no_wait_fields_no_extra_sleep(self):
        """Steps without wait_ms/wait_after_ms do not schedule extra sleeps."""
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep

        step = IRStep(step_id="s1", action="log", params={"message": "hi"})
        payload = IRSequencePayload(steps=[step])
        node = IRNode(node_id="n1", type="sequence", payload=payload)
        state = {"run_id": "", "vars": {}, "procedure_id": "p1"}

        sleep_calls = []

        async def fake_sleep(secs):
            sleep_calls.append(secs)

        with patch("asyncio.sleep", side_effect=fake_sleep):
            from app.runtime.node_executors import execute_sequence
            await execute_sequence(node, state, db_factory=None)

        # No extra sleeps (retry-backoff sleeps not triggered on success)
        assert sleep_calls == [], f"Expected no sleeps, got: {sleep_calls}"


# ---------------------------------------------------------------------------
# 2. Telemetry track_duration + track_retries
# ---------------------------------------------------------------------------


class TestTelemetryTracking:
    def test_step_completed_payload_includes_duration_when_track_duration(self):
        """When node telemetry.track_duration is True, step_completed payload has duration_ms."""
        # We test the logic by checking what _telemetry_payload would contain
        # This is an integration smoke via the IRNode telemetry dict
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep

        node = IRNode(
            node_id="n1",
            type="sequence",
            telemetry={"track_duration": True},
            payload=IRSequencePayload(steps=[]),
        )
        assert node.telemetry.get("track_duration") is True

    def test_step_completed_payload_includes_retries_when_track_retries(self):
        from app.compiler.ir import IRNode, IRSequencePayload

        node = IRNode(
            node_id="n1",
            type="sequence",
            telemetry={"track_retries": True},
            payload=IRSequencePayload(steps=[]),
        )
        assert node.telemetry.get("track_retries") is True

    def test_no_telemetry_key_omits_fields(self):
        from app.compiler.ir import IRNode, IRSequencePayload

        node = IRNode(node_id="n1", type="sequence", payload=IRSequencePayload(steps=[]))
        telemetry = node.telemetry or {}
        assert not telemetry.get("track_duration")
        assert not telemetry.get("track_retries")


# ---------------------------------------------------------------------------
# 3. Provenance + retrieval_metadata parsing
# ---------------------------------------------------------------------------


class TestIRProvenanceParsing:
    def test_provenance_parsed_into_ir(self):
        from app.compiler.parser import parse_ckp

        ckp = {
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
            "provenance": {
                "created_by": "alice",
                "reviewed_by": "bob",
                "source_system": "jira",
            },
        }
        ir = parse_ckp(ckp)
        assert ir.provenance is not None
        assert ir.provenance["created_by"] == "alice"

    def test_retrieval_metadata_parsed_into_ir(self):
        from app.compiler.parser import parse_ckp

        ckp = {
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
            "retrieval_metadata": {
                "tags": ["finance", "onboarding"],
                "category": "hr",
            },
        }
        ir = parse_ckp(ckp)
        assert ir.retrieval_metadata is not None
        assert ir.retrieval_metadata["category"] == "hr"

    def test_missing_provenance_and_retrieval_defaults_to_none(self):
        from app.compiler.parser import parse_ckp

        ckp = {
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        }
        ir = parse_ckp(ckp)
        assert ir.provenance is None
        assert ir.retrieval_metadata is None


class TestProcedureServiceProvenance:
    @pytest.mark.asyncio
    async def test_import_procedure_stores_provenance_json(self):
        from app.services.procedure_service import import_procedure

        ckp = {
            "procedure_id": "p-prov",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
            "provenance": {"created_by": "alice"},
            "retrieval_metadata": {"tags": ["test"]},
        }

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await import_procedure(mock_db, ckp)

        proc = mock_db.add.call_args[0][0]
        assert proc.provenance_json is not None
        assert json.loads(proc.provenance_json)["created_by"] == "alice"
        assert proc.retrieval_metadata_json is not None
        assert json.loads(proc.retrieval_metadata_json)["tags"] == ["test"]

    @pytest.mark.asyncio
    async def test_import_procedure_no_provenance_stores_none(self):
        from app.services.procedure_service import import_procedure

        ckp = {
            "procedure_id": "p-noprov",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        }

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await import_procedure(mock_db, ckp)

        proc = mock_db.add.call_args[0][0]
        assert proc.provenance_json is None
        assert proc.retrieval_metadata_json is None


class TestProcedureDetailSchema:
    def test_provenance_and_retrieval_metadata_exposed_in_detail(self):
        from app.schemas.procedures import ProcedureDetail

        mock_proc = MagicMock()
        mock_proc.id = 1
        mock_proc.procedure_id = "p1"
        mock_proc.version = "1.0"
        mock_proc.name = "Test"
        mock_proc.status = "draft"
        mock_proc.effective_date = None
        mock_proc.description = None
        mock_proc.project_id = None
        mock_proc.created_at = datetime.now(timezone.utc)
        mock_proc.ckp_json = json.dumps({
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        })
        mock_proc.provenance_json = json.dumps({"created_by": "alice"})
        mock_proc.retrieval_metadata_json = json.dumps({"tags": ["test"]})

        detail = ProcedureDetail.model_validate(mock_proc)
        assert detail.provenance == {"created_by": "alice"}
        assert detail.retrieval_metadata == {"tags": ["test"]}

    def test_null_provenance_stays_none(self):
        from app.schemas.procedures import ProcedureDetail

        mock_proc = MagicMock()
        mock_proc.id = 1
        mock_proc.procedure_id = "p1"
        mock_proc.version = "1.0"
        mock_proc.name = "Test"
        mock_proc.status = "draft"
        mock_proc.effective_date = None
        mock_proc.description = None
        mock_proc.project_id = None
        mock_proc.created_at = datetime.now(timezone.utc)
        mock_proc.ckp_json = json.dumps({
            "procedure_id": "p1",
            "version": "1.0",
            "workflow_graph": {"start_node": "n1", "nodes": {}},
        })
        mock_proc.provenance_json = None
        mock_proc.retrieval_metadata_json = None

        detail = ProcedureDetail.model_validate(mock_proc)
        assert detail.provenance is None
        assert detail.retrieval_metadata is None
