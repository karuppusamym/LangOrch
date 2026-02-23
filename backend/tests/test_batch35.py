"""Batch 35 — Agent Orchestration Mode tests.

Covers:
  1. IRLlmActionPayload gains orchestration_mode + branches fields (defaults)
  2. _parse_llm_action parses orchestration_mode and branches from CKP JSON
  3. execute_llm_action orchestration_mode: LLM's _next_node controls routing
  4. execute_llm_action orchestration_mode: invalid branch → fallback to first
  5. execute_llm_action orchestration_mode: bad JSON → fallback to first branch
  6. graph_builder uses conditional routing for orchestration_mode llm_action nodes
  7. Orchestration system_prompt injection includes branch list
"""

from __future__ import annotations

import json
from unittest.mock import patch, MagicMock


# ─── 1. IRLlmActionPayload new fields ────────────────────────────────────────

class TestIRLlmActionPayloadOrchestration:
    def test_defaults_are_false_and_empty(self):
        from app.compiler.ir import IRLlmActionPayload

        p = IRLlmActionPayload(prompt="hello")
        assert p.orchestration_mode is False
        assert p.branches == []

    def test_can_set_orchestration_mode_and_branches(self):
        from app.compiler.ir import IRLlmActionPayload

        p = IRLlmActionPayload(
            prompt="q",
            orchestration_mode=True,
            branches=["path_a", "path_b", "escalate"],
        )
        assert p.orchestration_mode is True
        assert p.branches == ["path_a", "path_b", "escalate"]


# ─── 2. Parser: _parse_llm_action reads orchestration fields ─────────────────

class TestParseLlmActionOrchestration:
    def test_parser_reads_orchestration_mode(self):
        from app.compiler.parser import _parse_llm_action

        payload = _parse_llm_action({
            "prompt": "Decide",
            "orchestration_mode": True,
            "branches": ["do_it", "skip_it"],
        })
        assert payload.orchestration_mode is True
        assert payload.branches == ["do_it", "skip_it"]

    def test_parser_defaults_to_non_orchestration(self):
        from app.compiler.parser import _parse_llm_action

        payload = _parse_llm_action({"prompt": "Hello"})
        assert payload.orchestration_mode is False
        assert payload.branches == []

    def test_parser_empty_branches_list(self):
        from app.compiler.parser import _parse_llm_action

        payload = _parse_llm_action({"prompt": "Hello", "orchestration_mode": True})
        assert payload.orchestration_mode is True
        assert payload.branches == []


# ─── 3-5. execute_llm_action orchestration routing ───────────────────────────

import pytest


class TestExecuteLlmActionOrchestration:
    @pytest.mark.asyncio
    async def test_llm_chosen_branch_becomes_next_node(self):
        """LLM returns {_next_node: path_b} → resolved_next == path_b."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="router",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Decide",
                orchestration_mode=True,
                branches=["path_a", "path_b", "escalate"],
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value
            instance.complete.return_value = {
                "text": json.dumps({"_next_node": "path_b", "reason": "complex case"}),
                "usage": {},
            }
            result = await execute_llm_action(node, state)

        assert result.get("next_node_id") == "path_b"
        assert result.get("terminal_status") != "failed"

    @pytest.mark.asyncio
    async def test_invalid_branch_falls_back_to_first(self):
        """LLM returns unknown branch → fallback to branches[0]."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="router",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Decide",
                orchestration_mode=True,
                branches=["safe_path", "risky_path"],
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value
            instance.complete.return_value = {
                "text": json.dumps({"_next_node": "nonexistent_branch"}),
                "usage": {},
            }
            result = await execute_llm_action(node, state)

        assert result.get("next_node_id") == "safe_path"

    @pytest.mark.asyncio
    async def test_bad_json_falls_back_to_first_branch(self):
        """LLM returns non-JSON text → fallback to branches[0]."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="router",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Decide",
                orchestration_mode=True,
                branches=["alpha", "beta"],
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value
            instance.complete.return_value = {
                "text": "I think alpha is better here because it is faster.",
                "usage": {},
            }
            result = await execute_llm_action(node, state)

        assert result.get("next_node_id") == "alpha"

    @pytest.mark.asyncio
    async def test_orchestration_mode_forces_json_mode(self):
        """When orchestration_mode=True, LLMClient.complete must be called with json_mode=True."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="router",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Choose",
                orchestration_mode=True,
                branches=["x", "y"],
                json_mode=False,  # manually off — orchestration_mode should override
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        captured_kwargs: dict = {}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value

            def _capture(*args, **kwargs):
                captured_kwargs.update(kwargs)
                return {"text": json.dumps({"_next_node": "x"}), "usage": {}}

            instance.complete.side_effect = _capture
            await execute_llm_action(node, state)

        assert captured_kwargs.get("json_mode") is True

    @pytest.mark.asyncio
    async def test_orchestration_mode_injects_branch_names_into_system_prompt(self):
        """The orchestration instruction containing branch names is appended to system_prompt."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="router",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Analyse and decide",
                orchestration_mode=True,
                branches=["fast_track", "deep_review"],
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        captured_kwargs: dict = {}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value

            def _capture(*args, **kwargs):
                captured_kwargs.update(kwargs)
                return {"text": json.dumps({"_next_node": "fast_track"}), "usage": {}}

            instance.complete.side_effect = _capture
            await execute_llm_action(node, state)

        system_prompt = captured_kwargs.get("system_prompt") or ""
        assert "fast_track" in system_prompt
        assert "deep_review" in system_prompt
        assert "_next_node" in system_prompt

    @pytest.mark.asyncio
    async def test_non_orchestration_mode_unchanged(self):
        """Normal llm_action routing is unaffected by the new code."""
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRLlmActionPayload, IRNode

        node = IRNode(
            node_id="classic",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Hello",
                outputs={"reply": "text"},
                next_node_id="next_step",
            ),
        )
        state = {"vars": {}, "run_id": "r1", "global_config": {}}

        with patch("app.connectors.llm_client.LLMClient") as MockLLM:
            instance = MockLLM.return_value
            instance.complete.return_value = {"text": "Hi there!", "usage": {}}
            result = await execute_llm_action(node, state)

        assert result.get("next_node_id") == "next_step"
        assert result["vars"].get("reply") == "Hi there!"


# ─── 6. graph_builder uses conditional routing for orchestration_mode nodes ───

class TestGraphBuilderOrchestrationRouting:
    def test_orchestration_mode_node_uses_conditional_edges(self):
        """graph_builder must call add_conditional_edges for orchestration_mode llm_action."""
        import inspect
        from app.runtime.graph_builder import build_graph

        src = inspect.getsource(build_graph)
        assert "orchestration_mode" in src, (
            "graph_builder.build_graph must handle orchestration_mode llm_action nodes"
        )

    def test_add_conditional_routing_handles_llm_action_branches(self):
        """_add_conditional_routing must collect branches from IRLlmActionPayload."""
        import inspect
        from app.runtime.graph_builder import _add_conditional_routing

        src = inspect.getsource(_add_conditional_routing)
        assert "IRLlmActionPayload" in src, (
            "_add_conditional_routing must handle IRLlmActionPayload branches"
        )
        assert "branches" in src, (
            "_add_conditional_routing must iterate payload.branches"
        )
