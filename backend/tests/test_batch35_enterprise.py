"""Batch 35 — Enterprise extensibility tests.

Covers:
  E1. Dynamic LLM client (base_url/api_key/extra_headers overrides)
  E2. LLM_GATEWAY_HEADERS parsed and merged into HTTP headers
  E3. _load_model_costs() reads LLM_MODEL_COST_JSON and merges with defaults
  E4. execute_llm_action raises LLMCallError instead of returning failed state
  E5. LLM circuit breaker opens after N failures, resets after timeout
  E6. MCP circuit breaker opens after N failures, resets after timeout
"""

import asyncio
import json
import unittest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pytest


# ─── E1. Dynamic LLM client overrides ────────────────────────────────────────


class TestLLMClientDynamicOverrides(unittest.TestCase):
    """LLMClient accepts per-call base_url, api_key, extra_headers."""

    def test_default_uses_settings(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = None

            from app.connectors.llm_client import LLMClient
            client = LLMClient()
            assert client.base_url == "https://api.openai.com/v1"
            assert client.api_key == "sk-test"

    def test_override_base_url(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = None

            from app.connectors.llm_client import LLMClient
            client = LLMClient(base_url="https://custom.gateway.com/v1")
            assert client.base_url == "https://custom.gateway.com/v1"

    def test_override_api_key(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-default"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = None

            from app.connectors.llm_client import LLMClient
            client = LLMClient(api_key="sk-tenant-specific")
            assert client.api_key == "sk-tenant-specific"

    def test_extra_headers_merged(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = None

            from app.connectors.llm_client import LLMClient
            client = LLMClient(extra_headers={"X-Tenant-ID": "acme"})
            assert client._extra_headers == {"X-Tenant-ID": "acme"}


# ─── E2. LLM_GATEWAY_HEADERS from config ─────────────────────────────────────


class TestLLMGatewayHeaders(unittest.TestCase):
    """LLM_GATEWAY_HEADERS setting is parsed and merged into client headers."""

    def test_gateway_headers_parsed_from_json(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = '{"X-Gateway": "prod", "X-Org": "123"}'

            from app.connectors.llm_client import LLMClient
            client = LLMClient()
            assert client._extra_headers["X-Gateway"] == "prod"
            assert client._extra_headers["X-Org"] == "123"

    def test_gateway_headers_plus_extra_headers_merged(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = '{"X-Gateway": "prod"}'

            from app.connectors.llm_client import LLMClient
            client = LLMClient(extra_headers={"X-Tenant-ID": "acme"})
            assert client._extra_headers["X-Gateway"] == "prod"
            assert client._extra_headers["X-Tenant-ID"] == "acme"

    def test_invalid_gateway_headers_ignored(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = "not-valid-json"

            from app.connectors.llm_client import LLMClient
            client = LLMClient()
            assert client._extra_headers == {}

    def test_per_call_headers_override_gateway(self):
        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = '{"X-Gateway": "dev"}'

            from app.connectors.llm_client import LLMClient
            client = LLMClient(extra_headers={"X-Gateway": "prod-override"})
            # Per-call should win over config
            assert client._extra_headers["X-Gateway"] == "prod-override"


# ─── E3. Externalised model cost table ────────────────────────────────────────


class TestExternalisedModelCosts(unittest.TestCase):
    """_load_model_costs() reads LLM_MODEL_COST_JSON and merges with defaults."""

    def test_defaults_present_without_override(self):
        with patch("app.runtime.node_executors.settings") as mock_settings:
            mock_settings.LLM_MODEL_COST_JSON = None
            from app.runtime.node_executors import _load_model_costs
            costs = _load_model_costs()
            assert "gpt-4" in costs
            assert "gpt-4o" in costs
            assert costs["gpt-4"]["prompt"] == 0.03

    def test_override_existing_model(self):
        override = json.dumps({"gpt-4": {"prompt": 0.02, "completion": 0.04}})
        with patch("app.runtime.node_executors.settings") as mock_settings:
            mock_settings.LLM_MODEL_COST_JSON = override
            from app.runtime.node_executors import _load_model_costs
            costs = _load_model_costs()
            assert costs["gpt-4"]["prompt"] == 0.02
            assert costs["gpt-4"]["completion"] == 0.04

    def test_add_new_model(self):
        override = json.dumps({"llama-3-70b": {"prompt": 0.001, "completion": 0.002}})
        with patch("app.runtime.node_executors.settings") as mock_settings:
            mock_settings.LLM_MODEL_COST_JSON = override
            from app.runtime.node_executors import _load_model_costs
            costs = _load_model_costs()
            assert "llama-3-70b" in costs
            assert costs["llama-3-70b"]["prompt"] == 0.001
            # Defaults still present
            assert "gpt-4o" in costs

    def test_invalid_json_uses_defaults(self):
        with patch("app.runtime.node_executors.settings") as mock_settings:
            mock_settings.LLM_MODEL_COST_JSON = "{{invalid"
            from app.runtime.node_executors import _load_model_costs
            costs = _load_model_costs()
            assert "gpt-4" in costs
            assert costs["gpt-4"]["prompt"] == 0.03

    def test_model_name_lowercased(self):
        override = json.dumps({"GPT-4o-MINI": {"prompt": 0.001, "completion": 0.002}})
        with patch("app.runtime.node_executors.settings") as mock_settings:
            mock_settings.LLM_MODEL_COST_JSON = override
            from app.runtime.node_executors import _load_model_costs
            costs = _load_model_costs()
            assert "gpt-4o-mini" in costs


# ─── E4. LLM failure raises exception ────────────────────────────────────────


class TestLLMFailureRaisesException:
    """execute_llm_action raises LLMCallError instead of returning failed state."""

    @pytest.mark.asyncio
    async def test_llm_failure_raises_not_returns(self):
        from app.connectors.llm_client import LLMCallError
        from app.runtime.node_executors import execute_llm_action
        from app.compiler.ir import IRNode, IRLlmActionPayload

        node = IRNode(
            node_id="test-llm",
            type="llm_action",
            payload=IRLlmActionPayload(
                prompt="Hello",
                model="gpt-4",
                temperature=0.7,
                max_tokens=100,
                system_prompt=None,
                json_mode=False,
                outputs={},
                retry={"max_retries": 0},
                orchestration_mode=False,
                branches=[],
            ),
            next_node_id=None,
        )
        state = {"vars": {}, "run_id": "r1", "procedure_id": "p1", "global_config": {"max_retries": 0}}

        # asyncio.to_thread calls LLMClient().complete(...) — we patch to_thread
        # so that it raises directly instead of spinning a real thread.
        async def fake_to_thread(fn, *args, **kwargs):
            raise LLMCallError("test error")

        with patch("app.runtime.node_executors.asyncio") as mock_asyncio:
            mock_asyncio.to_thread = fake_to_thread
            mock_asyncio.sleep = asyncio.sleep  # keep real sleep

            with pytest.raises(LLMCallError, match="test error"):
                await execute_llm_action(node, state)


# ─── E5. LLM circuit breaker ─────────────────────────────────────────────────


class TestLLMCircuitBreaker(unittest.TestCase):
    """LLM circuit breaker opens after N failures, resets after timeout."""

    def setUp(self):
        from app.connectors.llm_client import reset_llm_circuit_breaker
        reset_llm_circuit_breaker()

    def tearDown(self):
        from app.connectors.llm_client import reset_llm_circuit_breaker
        reset_llm_circuit_breaker()

    def test_circuit_stays_closed_under_threshold(self):
        import app.connectors.llm_client as mod
        for _ in range(mod._LLM_CIRCUIT_THRESHOLD - 1):
            mod._record_llm_failure()
        # Should NOT raise
        mod._check_llm_circuit()

    def test_circuit_opens_at_threshold(self):
        import app.connectors.llm_client as mod
        from app.connectors.llm_client import LLMCallError
        for _ in range(mod._LLM_CIRCUIT_THRESHOLD):
            mod._record_llm_failure()
        with self.assertRaises(LLMCallError) as ctx:
            mod._check_llm_circuit()
        assert "circuit breaker open" in str(ctx.exception)

    def test_circuit_resets_after_timeout(self):
        import app.connectors.llm_client as mod
        for _ in range(mod._LLM_CIRCUIT_THRESHOLD):
            mod._record_llm_failure()
        # Simulate timeout elapsed
        mod._llm_circuit_open_at = datetime.now(timezone.utc) - timedelta(
            seconds=mod._LLM_CIRCUIT_RESET_SECONDS + 1
        )
        # Should NOT raise — circuit auto-resets
        mod._check_llm_circuit()
        assert mod._llm_circuit_open_at is None

    def test_success_resets_counter(self):
        import app.connectors.llm_client as mod
        for _ in range(mod._LLM_CIRCUIT_THRESHOLD - 1):
            mod._record_llm_failure()
        mod._record_llm_success()
        assert mod._llm_consecutive_failures == 0
        # More failures after reset — should need full threshold again
        for _ in range(mod._LLM_CIRCUIT_THRESHOLD - 1):
            mod._record_llm_failure()
        mod._check_llm_circuit()  # Should NOT raise


# ─── E6. MCP circuit breaker ─────────────────────────────────────────────────


class TestMCPCircuitBreaker(unittest.TestCase):
    """MCP circuit breaker opens after N failures, resets after timeout."""

    def setUp(self):
        from app.connectors.mcp_client import reset_mcp_circuit_breaker
        reset_mcp_circuit_breaker()

    def tearDown(self):
        from app.connectors.mcp_client import reset_mcp_circuit_breaker
        reset_mcp_circuit_breaker()

    def test_circuit_stays_closed_under_threshold(self):
        import app.connectors.mcp_client as mod
        for _ in range(mod._MCP_CIRCUIT_THRESHOLD - 1):
            mod._record_mcp_failure()
        # Should NOT raise
        mod._check_mcp_circuit()

    def test_circuit_opens_at_threshold(self):
        import app.connectors.mcp_client as mod
        from app.connectors.mcp_client import MCPToolError
        for _ in range(mod._MCP_CIRCUIT_THRESHOLD):
            mod._record_mcp_failure()
        with self.assertRaises(MCPToolError) as ctx:
            mod._check_mcp_circuit()
        assert "circuit breaker open" in str(ctx.exception)

    def test_circuit_resets_after_timeout(self):
        import app.connectors.mcp_client as mod
        for _ in range(mod._MCP_CIRCUIT_THRESHOLD):
            mod._record_mcp_failure()
        # Simulate timeout elapsed
        mod._mcp_circuit_open_at = datetime.now(timezone.utc) - timedelta(
            seconds=mod._MCP_CIRCUIT_RESET_SECONDS + 1
        )
        # Should NOT raise — circuit auto-resets
        mod._check_mcp_circuit()
        assert mod._mcp_circuit_open_at is None

    def test_success_resets_counter(self):
        import app.connectors.mcp_client as mod
        for _ in range(mod._MCP_CIRCUIT_THRESHOLD - 1):
            mod._record_mcp_failure()
        mod._record_mcp_success()
        assert mod._mcp_consecutive_failures == 0
        # More failures after reset — should need full threshold again
        for _ in range(mod._MCP_CIRCUIT_THRESHOLD - 1):
            mod._record_mcp_failure()
        mod._check_mcp_circuit()  # Should NOT raise


# ─── E2+E5 integration: LLMClient.complete with circuit breaker ──────────────


class TestLLMClientComplete(unittest.TestCase):
    """LLMClient.complete respects circuit breaker state."""

    def setUp(self):
        from app.connectors.llm_client import reset_llm_circuit_breaker
        reset_llm_circuit_breaker()

    def tearDown(self):
        from app.connectors.llm_client import reset_llm_circuit_breaker
        reset_llm_circuit_breaker()

    def test_complete_rejects_when_circuit_open(self):
        import app.connectors.llm_client as mod
        from app.connectors.llm_client import LLMCallError, LLMClient

        for _ in range(mod._LLM_CIRCUIT_THRESHOLD):
            mod._record_llm_failure()

        with patch("app.connectors.llm_client.settings") as mock_settings:
            mock_settings.LLM_BASE_URL = "https://api.openai.com/v1"
            mock_settings.LLM_API_KEY = "sk-test"
            mock_settings.LLM_TIMEOUT_SECONDS = 30.0
            mock_settings.LLM_GATEWAY_HEADERS = None

            client = LLMClient()
            with self.assertRaises(LLMCallError) as ctx:
                client.complete("hello", model="gpt-4")
            assert "circuit breaker open" in str(ctx.exception)
