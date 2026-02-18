"""Tests for Batch 9 backend features:
  1. run_cancel — in-process asyncio.Event cancellation registry
  2. execute_sequence cancel propagation
  3. LLM system_prompt + json_mode (IR, parser, llm_client)
  4. Approval expires_at / expiry service
"""

from __future__ import annotations

import asyncio
import json
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

# ---------------------------------------------------------------------------
# 1. run_cancel utility
# ---------------------------------------------------------------------------


class TestRunCancel:
    def setup_method(self):
        from app.utils.run_cancel import _events
        _events.clear()

    def test_register_creates_event(self):
        from app.utils.run_cancel import register, _events
        register("run-1")
        assert "run-1" in _events

    def test_is_cancelled_false_after_register(self):
        from app.utils.run_cancel import register, is_cancelled
        register("run-2")
        assert not is_cancelled("run-2")

    def test_mark_cancelled_sets_event(self):
        from app.utils.run_cancel import register, mark_cancelled, is_cancelled
        register("run-3")
        mark_cancelled("run-3")
        assert is_cancelled("run-3")

    def test_deregister_removes_event(self):
        from app.utils.run_cancel import register, deregister, _events
        register("run-4")
        deregister("run-4")
        assert "run-4" not in _events

    def test_is_cancelled_unknown_run_returns_false(self):
        from app.utils.run_cancel import is_cancelled
        assert not is_cancelled("nonexistent-run")

    def test_mark_cancelled_unknown_run_is_noop(self):
        """mark_cancelled on unregistered run should not raise."""
        from app.utils.run_cancel import mark_cancelled
        mark_cancelled("ghost-run")  # no error

    def test_deregister_unknown_run_is_noop(self):
        from app.utils.run_cancel import deregister
        deregister("ghost-run")  # no error

    def test_run_cancelled_error_is_exception(self):
        from app.utils.run_cancel import RunCancelledError
        with pytest.raises(RunCancelledError):
            raise RunCancelledError("cancelled")


# ---------------------------------------------------------------------------
# 2. execute_sequence cancel propagation
# ---------------------------------------------------------------------------


class TestExecuteSequenceCancelPropagation:
    @pytest.mark.asyncio
    async def test_cancel_raises_before_step_executes(self):
        """Steps should not run if run is already cancelled."""
        from app.utils.run_cancel import register, mark_cancelled, deregister, RunCancelledError
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep
        from app.runtime.node_executors import execute_sequence

        run_id = "seq-cancel-1"
        register(run_id)
        mark_cancelled(run_id)

        step = IRStep(step_id="s1", action="log", params={"message": "should not run"})
        payload = IRSequencePayload(steps=[step])
        node = IRNode(node_id="n1", type="sequence", payload=payload)
        state = {
            "run_id": run_id,
            "vars": {},
            "procedure_id": "proc-1",
        }

        with pytest.raises(RunCancelledError):
            await execute_sequence(node, state, db_factory=None)
        deregister(run_id)

    @pytest.mark.asyncio
    async def test_no_cancel_runs_steps_normally(self):
        """Steps run normally when run is not cancelled."""
        from app.utils.run_cancel import register, is_cancelled
        from app.compiler.ir import IRNode, IRSequencePayload, IRStep
        from app.runtime.node_executors import execute_sequence

        run_id = "seq-cancel-2"
        register(run_id)
        assert not is_cancelled(run_id)

        step = IRStep(step_id="s1", action="log", params={"message": "hello"})
        payload = IRSequencePayload(steps=[step])
        node = IRNode(node_id="n1", type="sequence", payload=payload)
        state = {
            "run_id": run_id,
            "vars": {},
            "procedure_id": "proc-1",
        }

        # Should complete without raising; log action returns None result
        result = await execute_sequence(node, state, db_factory=None)
        assert result is not None

        from app.utils.run_cancel import deregister
        deregister(run_id)


# ---------------------------------------------------------------------------
# 3. LLM system_prompt + json_mode
# ---------------------------------------------------------------------------


class TestIRLlmActionPayloadFields:
    def test_default_values(self):
        from app.compiler.ir import IRLlmActionPayload
        p = IRLlmActionPayload(prompt="hello")
        assert p.system_prompt is None
        assert p.json_mode is False

    def test_explicit_values(self):
        from app.compiler.ir import IRLlmActionPayload
        p = IRLlmActionPayload(prompt="q", system_prompt="You are helpful.", json_mode=True)
        assert p.system_prompt == "You are helpful."
        assert p.json_mode is True


class TestParserLlmAction:
    def test_parses_system_prompt_and_json_mode(self):
        from app.compiler.parser import _parse_llm_action
        payload = _parse_llm_action({
            "prompt": "Hello",
            "model": "gpt-4",
            "system_prompt": "Be concise.",
            "json_mode": True,
        })
        assert payload.system_prompt == "Be concise."
        assert payload.json_mode is True

    def test_defaults_when_missing(self):
        from app.compiler.parser import _parse_llm_action
        payload = _parse_llm_action({"prompt": "Hello"})
        assert payload.system_prompt is None
        assert payload.json_mode is False


class TestLLMClientSystemPrompt:
    def test_system_message_prepended(self):
        """When system_prompt is set, a system role message is added to body."""
        from app.connectors.llm_client import LLMClient

        client = LLMClient()
        client.api_key = "test-key"

        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured["body"] = json
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "ok"}}]
            }
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.post = fake_post
            mock_client_cls.return_value = mock_ctx

            client.complete(
                prompt="User question",
                model="gpt-4",
                system_prompt="Be helpful.",
            )

        messages = captured["body"]["messages"]
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "Be helpful."
        assert messages[1]["role"] == "user"

    def test_json_mode_adds_response_format(self):
        from app.connectors.llm_client import LLMClient

        client = LLMClient()
        client.api_key = "test-key"
        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured["body"] = json
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "{}"}}]
            }
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.post = fake_post
            mock_client_cls.return_value = mock_ctx

            client.complete(prompt="q", model="gpt-4", json_mode=True)

        assert captured["body"].get("response_format") == {"type": "json_object"}

    def test_no_system_prompt_omits_system_message(self):
        from app.connectors.llm_client import LLMClient

        client = LLMClient()
        client.api_key = "test-key"
        captured = {}

        def fake_post(url, json=None, **kwargs):
            captured["body"] = json
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "choices": [{"message": {"content": "answer"}}]
            }
            mock_resp.raise_for_status = MagicMock()
            return mock_resp

        with patch("httpx.Client") as mock_client_cls:
            mock_ctx = MagicMock()
            mock_ctx.__enter__ = MagicMock(return_value=mock_ctx)
            mock_ctx.__exit__ = MagicMock(return_value=False)
            mock_ctx.post = fake_post
            mock_client_cls.return_value = mock_ctx

            client.complete(prompt="q", model="gpt-4")

        messages = captured["body"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"


# ---------------------------------------------------------------------------
# 4. Approval expires_at
# ---------------------------------------------------------------------------


class TestApprovalExpiresAt:
    @pytest.mark.asyncio
    async def test_create_approval_sets_expires_at_when_timeout_ms_given(self):
        from app.services.approval_service import create_approval

        mock_approval = MagicMock()
        mock_approval.approval_id = "appr-1"

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        before = datetime.now(timezone.utc)

        # Patch so db.refresh sets the object's expires_at from our captured call
        captured = {}

        async def fake_refresh(obj):
            captured["approval"] = obj

        mock_db.refresh.side_effect = fake_refresh

        await create_approval(
            mock_db,
            run_id="run-1",
            node_id="node-1",
            prompt="Approve?",
            decision_type="approve_reject",
            timeout_ms=60_000,
        )

        approval_obj = mock_db.add.call_args[0][0]
        assert approval_obj.expires_at is not None
        delta = approval_obj.expires_at - before
        # Should be ~60 seconds ahead
        assert 59 <= delta.total_seconds() <= 62

    @pytest.mark.asyncio
    async def test_create_approval_no_expires_at_when_no_timeout(self):
        from app.services.approval_service import create_approval

        mock_db = AsyncMock()
        mock_db.add = MagicMock()
        mock_db.flush = AsyncMock()
        mock_db.refresh = AsyncMock()

        await create_approval(
            mock_db,
            run_id="run-2",
            node_id="node-2",
            prompt="Approve?",
            decision_type="approve_reject",
        )

        approval_obj = mock_db.add.call_args[0][0]
        assert approval_obj.expires_at is None

    @pytest.mark.asyncio
    async def test_get_expired_approvals_returns_past_expiry(self):
        from app.services.approval_service import get_expired_approvals
        from app.db.models import Approval

        past = datetime.now(timezone.utc) - timedelta(seconds=10)
        expired_appr = Approval(
            approval_id="appr-expired",
            run_id="run-x",
            node_id="n1",
            prompt="p",
            decision_type="approve_reject",
            status="pending",
        )
        expired_appr.expires_at = past

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [expired_appr]

        mock_db = AsyncMock()
        mock_db.execute = AsyncMock(return_value=mock_result)

        results = await get_expired_approvals(mock_db)
        assert len(results) == 1
        assert results[0].approval_id == "appr-expired"
