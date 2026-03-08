"""Tests for LLM fallback policy service."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.services.llm_fallback_service import (
    LLMFallbackPolicy,
    get_fallback_policy,
    reset_fallback_policy,
)
from app.connectors.llm_client import LLMCallError


class TestLLMFallbackPolicy:
    """Tests for LLM fallback policy."""

    def test_get_fallback_chain(self):
        """Test getting fallback chain for a model."""
        policy = LLMFallbackPolicy()
        
        # GPT-4 should fallback to cheaper models
        chain = policy.get_fallback_chain("gpt-4-turbo")
        assert "gpt-4" in chain
        assert "gpt-3.5-turbo" in chain
        
        # Unknown model should return empty list
        chain = policy.get_fallback_chain("unknown-model")
        assert chain == []

    def test_get_model_cost(self):
        """Test getting cost metrics for a model."""
        policy = LLMFallbackPolicy()
        
        cost = policy.get_model_cost("gpt-4")
        assert "prompt" in cost
        assert "completion" in cost
        assert "quality" in cost
        assert cost["quality"] > 0
        
        # Unknown model should return default
        cost = policy.get_model_cost("unknown-model")
        assert cost["prompt"] > 0

    def test_estimate_call_cost(self):
        """Test cost estimation."""
        policy = LLMFallbackPolicy()
        
        # GPT-4 should be more expensive than GPT-3.5
        gpt4_cost = policy.estimate_call_cost("gpt-4", 1000, 1000)
        gpt35_cost = policy.estimate_call_cost("gpt-3.5-turbo", 1000, 1000)
        
        assert gpt4_cost > gpt35_cost
        assert gpt4_cost > 0

    def test_should_fallback(self):
        """Test fallback decision logic."""
        policy = LLMFallbackPolicy()
        
        # Circuit breaker should trigger fallback
        assert policy.should_fallback(LLMCallError("LLM circuit breaker open"))
        
        # Rate limit should trigger fallback
        assert policy.should_fallback(LLMCallError("HTTP 429"))
        
        # Service unavailable should trigger fallback
        assert policy.should_fallback(LLMCallError("HTTP 503"))
        
        # Timeout should trigger fallback
        assert policy.should_fallback(LLMCallError("Timeout exceeded"))
        
        # Other errors should not trigger fallback
        assert not policy.should_fallback(LLMCallError("Invalid API key"))

    @pytest.mark.asyncio
    async def test_complete_with_fallback_success_first_try(self):
        """Test successful completion on first try."""
        policy = LLMFallbackPolicy()
        
        mock_result = {
            "text": "Hello world",
            "raw": {},
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            mock_client.return_value.complete = MagicMock(return_value=mock_result)
            
            result = await policy.complete_with_fallback(
                prompt="Test prompt",
                model="gpt-4",
            )
            
            assert result["text"] == "Hello world"
            assert result["model_used"] == "gpt-4"
            assert result["fallback_attempt"] == 0

    @pytest.mark.asyncio
    async def test_complete_with_fallback_success_after_retry(self):
        """Test fallback to cheaper model after primary fails."""
        policy = LLMFallbackPolicy(
            fallback_chains={"gpt-4": ["gpt-3.5-turbo"]}
        )
        
        mock_success_result = {
            "text": "Fallback response",
            "raw": {},
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            # First call (gpt-4) fails with rate limit
            # Second call (gpt-3.5-turbo) succeeds
            mock_instance = mock_client.return_value
            mock_instance.complete = MagicMock(
                side_effect=[
                    LLMCallError("HTTP 429"),  # First fails
                    mock_success_result,  # Second succeeds
                ]
            )
            
            result = await policy.complete_with_fallback(
                prompt="Test prompt",
                model="gpt-4",
            )
            
            assert result["text"] == "Fallback response"
            assert result["model_used"] == "gpt-3.5-turbo"
            assert result["fallback_attempt"] == 1
            assert result["primary_model"] == "gpt-4"
            
            # Should have tried gpt-4 then gpt-3.5-turbo
            assert mock_instance.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_complete_with_fallback_all_fail(self):
        """Test failure when all models in chain fail."""
        policy = LLMFallbackPolicy(
            fallback_chains={"gpt-4": ["gpt-3.5-turbo"]}
        )
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            mock_instance = mock_client.return_value
            mock_instance.complete = MagicMock(
                side_effect=LLMCallError("HTTP 503")
            )
            
            with pytest.raises(LLMCallError) as exc_info:
                await policy.complete_with_fallback(
                    prompt="Test prompt",
                    model="gpt-4",
                )
            
            assert "All models in fallback chain failed" in str(exc_info.value)
            # Should have tried both models
            assert mock_instance.complete.call_count == 2

    @pytest.mark.asyncio
    async def test_complete_with_cost_constraint(self):
        """Test that expensive models are skipped when cost constraint is set."""
        policy = LLMFallbackPolicy(
            model_costs={
                "expensive-model": {"prompt": 1.0, "completion": 2.0, "quality": 95},
                "cheap-model": {"prompt": 0.001, "completion": 0.002, "quality": 80},
            },
            fallback_chains={"expensive-model": ["cheap-model"]},
        )
        
        mock_result = {
            "text": "Response",
            "raw": {},
            "usage": {"prompt_tokens": 10, "completion_tokens": 20},
        }
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            mock_instance = mock_client.return_value
            mock_instance.complete = MagicMock(
                side_effect=[
                    LLMCallError("HTTP 429"),  # Expensive fails
                    mock_result,  # Cheap succeeds
                ]
            )
            
            result = await policy.complete_with_fallback(
                prompt="Test prompt",
                model="expensive-model",
                max_cost_usd=0.01,  # Very low cost limit
            )
            
            # Should have skipped expensive-model and used cheap-model
            assert result["model_used"] == "cheap-model"

    @pytest.mark.asyncio
    async def test_complete_with_quality_constraint(self):
        """Test that low-quality models are skipped when quality constraint is set."""
        policy = LLMFallbackPolicy(
            model_costs={
                "high-quality": {"prompt": 0.01, "completion": 0.03, "quality": 95},
                "low-quality": {"prompt": 0.001, "completion": 0.002, "quality": 60},
            },
            fallback_chains={"high-quality": ["low-quality"]},
        )
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            mock_instance = mock_client.return_value
            mock_instance.complete = MagicMock(
                side_effect=LLMCallError("HTTP 429")
            )
            
            with pytest.raises(LLMCallError) as exc_info:
                await policy.complete_with_fallback(
                    prompt="Test prompt",
                    model="high-quality",
                    min_quality=80,  # Require min quality 80
                )
            
            # low-quality model (60) should have been skipped
            assert "No suitable models found" in str(exc_info.value)
            # Only tried high-quality, skipped low-quality
            assert mock_instance.complete.call_count == 1

    @pytest.mark.asyncio
    async def test_complete_non_retriable_error_aborts_chain(self):
        """Test that non-retriable errors don't trigger fallback."""
        policy = LLMFallbackPolicy(
            fallback_chains={"gpt-4": ["gpt-3.5-turbo"]}
        )
        
        with patch("app.services.llm_fallback_service.LLMClient") as mock_client:
            mock_instance = mock_client.return_value
            # Non-retriable error (invalid API key)
            mock_instance.complete = MagicMock(
                side_effect=LLMCallError("Invalid API key")
            )
            
            with pytest.raises(LLMCallError) as exc_info:
                await policy.complete_with_fallback(
                    prompt="Test prompt",
                    model="gpt-4",
                )
            
            # Should fail immediately without trying fallback
            assert mock_instance.complete.call_count == 1
            assert "Invalid API key" in str(exc_info.value)


class TestFallbackPolicySingleton:
    """Tests for singleton pattern."""

    def test_get_fallback_policy_returns_same_instance(self):
        """Test that get_fallback_policy returns singleton."""
        reset_fallback_policy()
        
        policy1 = get_fallback_policy()
        policy2 = get_fallback_policy()
        
        assert policy1 is policy2

    def test_reset_fallback_policy(self):
        """Test that reset creates new instance."""
        policy1 = get_fallback_policy()
        reset_fallback_policy()
        policy2 = get_fallback_policy()
        
        assert policy1 is not policy2
