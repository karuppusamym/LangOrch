"""LLM Fallback Policy Service

Implements automatic fallback chains for LLM calls with cost/quality constraints.

Example fallback chain:
  1. Primary: gpt-4-turbo (high quality, high cost)
  2. Fallback 1: gpt-4 (good quality, medium cost)
  3. Fallback 2: gpt-3.5-turbo (acceptable quality, low cost)

Fallback triggers:
  - Circuit breaker open
  - HTTP 429 (rate limit)
  - HTTP 503 (service unavailable)
  - Timeout
  - Other network errors
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from app.connectors.llm_client import LLMCallError, LLMClient
from app.config import settings

logger = logging.getLogger("langorch.services.llm_fallback")

# ── Default Model Cost Table (USD per 1K tokens) ──────────────────────────────
DEFAULT_MODEL_COSTS = {
    "gpt-4-turbo": {"prompt": 0.01, "completion": 0.03, "quality": 95},
    "gpt-4": {"prompt": 0.03, "completion": 0.06, "quality": 95},
    "gpt-4-32k": {"prompt": 0.06, "completion": 0.12, "quality": 95},
    "gpt-3.5-turbo": {"prompt": 0.0015, "completion": 0.002, "quality": 80},
    "gpt-3.5-turbo-16k": {"prompt": 0.003, "completion": 0.004, "quality": 80},
    "claude-3-opus": {"prompt": 0.015, "completion": 0.075, "quality": 97},
    "claude-3-sonnet": {"prompt": 0.003, "completion": 0.015, "quality": 92},
    "claude-3-haiku": {"prompt": 0.00025, "completion": 0.00125, "quality": 85},
    "mistral-large": {"prompt": 0.008, "completion": 0.024, "quality": 90},
    "mistral-medium": {"prompt": 0.0027, "completion": 0.0081, "quality": 85},
    "mistral-small": {"prompt": 0.001, "completion": 0.003, "quality": 75},
}

# ── Default Fallback Chains ───────────────────────────────────────────────────
DEFAULT_FALLBACK_CHAINS = {
    "gpt-4-turbo": ["gpt-4", "gpt-3.5-turbo"],
    "gpt-4": ["gpt-3.5-turbo-16k", "gpt-3.5-turbo"],
    "gpt-4-32k": ["gpt-4", "gpt-3.5-turbo-16k"],
    "claude-3-opus": ["claude-3-sonnet", "claude-3-haiku"],
    "claude-3-sonnet": ["claude-3-haiku"],
    "mistral-large": ["mistral-medium", "mistral-small"],
    "mistral-medium": ["mistral-small"],
}


class LLMFallbackPolicy:
    """Manages LLM fallback chains with cost and quality constraints."""

    def __init__(
        self,
        model_costs: dict[str, dict[str, float]] | None = None,
        fallback_chains: dict[str, list[str]] | None = None,
    ):
        """Initialize fallback policy.

        Args:
            model_costs: Per-model cost and quality metrics. Merges with defaults.
            fallback_chains: Model → [fallback models] mapping. Merges with defaults.
        """
        self.model_costs = {**DEFAULT_MODEL_COSTS}
        if model_costs:
            self.model_costs.update(model_costs)

        self.fallback_chains = {**DEFAULT_FALLBACK_CHAINS}
        if fallback_chains:
            self.fallback_chains.update(fallback_chains)

        # Load custom cost table from config if provided
        if settings.LLM_MODEL_COST_JSON:
            try:
                import json
                custom_costs = json.loads(settings.LLM_MODEL_COST_JSON)
                if isinstance(custom_costs, dict):
                    self.model_costs.update(custom_costs)
                    logger.info("Loaded %d custom model cost entries", len(custom_costs))
            except (json.JSONDecodeError, ValueError) as exc:
                logger.warning("Failed to parse LLM_MODEL_COST_JSON: %s", exc)

    def get_fallback_chain(self, model: str) -> list[str]:
        """Get fallback model chain for a given primary model.

        Args:
            model: Primary model name

        Returns:
            List of fallback model names (empty if no fallbacks configured)
        """
        return self.fallback_chains.get(model, [])

    def get_model_cost(self, model: str) -> dict[str, float]:
        """Get cost and quality metrics for a model.

        Args:
            model: Model name

        Returns:
            Dict with 'prompt', 'completion', and 'quality' keys
        """
        return self.model_costs.get(model, {"prompt": 0.01, "completion": 0.03, "quality": 80})

    def estimate_call_cost(self, model: str, prompt_tokens: int, completion_tokens: int) -> float:
        """Estimate cost for an LLM call.

        Args:
            model: Model name
            prompt_tokens: Number of prompt tokens
            completion_tokens: Number of completion tokens

        Returns:
            Estimated cost in USD
        """
        costs = self.get_model_cost(model)
        return (prompt_tokens * costs["prompt"] + completion_tokens * costs["completion"]) / 1000.0

    def should_fallback(self, exception: Exception) -> bool:
        """Determine if an error should trigger fallback.

        Args:
            exception: Exception raised by LLM call

        Returns:
            True if fallback should be attempted
        """
        if not isinstance(exception, LLMCallError):
            return False

        error_msg = str(exception).lower()

        # Fallback triggers
        triggers = [
            "circuit breaker open",  # Circuit breaker
            "429",  # Rate limit
            "503",  # Service unavailable
            "timeout",  # Timeout
            "connection",  # Connection errors
            "network",  # Network errors
        ]

        return any(trigger in error_msg for trigger in triggers)

    async def complete_with_fallback(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        json_mode: bool = False,
        max_cost_usd: float | None = None,
        min_quality: int | None = None,
    ) -> dict[str, Any]:
        """Execute LLM completion with automatic fallback on failure.

        Args:
            prompt: User prompt
            model: Primary model name
            temperature: Sampling temperature
            max_tokens: Max completion tokens
            system_prompt: System prompt
            json_mode: Force JSON output
            max_cost_usd: Maximum acceptable cost per call (None = no limit)
            min_quality: Minimum quality score (0-100, None = no limit)

        Returns:
            LLM response dict with 'text', 'raw', 'usage', and 'model_used' keys

        Raises:
            LLMCallError: If all models in fallback chain fail
        """
        models_to_try = [model] + self.get_fallback_chain(model)
        last_exception: Exception | None = None

        for attempt_idx, current_model in enumerate(models_to_try):
            # Quality constraint check
            if min_quality is not None:
                model_quality = self.get_model_cost(current_model).get("quality", 80)
                if model_quality < min_quality:
                    logger.info(
                        "Skipping %s: quality %d < min_quality %d",
                        current_model, model_quality, min_quality,
                    )
                    continue

            # Cost constraint check (estimate assuming 1000 tokens each)
            if max_cost_usd is not None:
                estimated_cost = self.estimate_call_cost(current_model, 1000, 1000)
                if estimated_cost > max_cost_usd:
                    logger.info(
                        "Skipping %s: estimated cost $%.4f > max_cost_usd $%.4f",
                        current_model, estimated_cost, max_cost_usd,
                    )
                    continue

            try:
                logger.info(
                    "LLM fallback attempt %d/%d: model=%s",
                    attempt_idx + 1, len(models_to_try), current_model,
                )

                result = await asyncio.to_thread(
                    LLMClient().complete,
                    prompt=prompt,
                    model=current_model,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    system_prompt=system_prompt,
                    json_mode=json_mode,
                )

                # Success! Add metadata about which model was used
                result["model_used"] = current_model
                result["fallback_attempt"] = attempt_idx
                result["primary_model"] = model

                if attempt_idx > 0:
                    logger.info(
                        "LLM fallback succeeded: %s → %s (attempt %d)",
                        model, current_model, attempt_idx + 1,
                    )

                return result

            except LLMCallError as exc:
                last_exception = exc
                logger.warning(
                    "LLM call failed with %s: %s",
                    current_model, exc,
                )

                # Check if we should try fallback
                if attempt_idx < len(models_to_try) - 1:
                    if self.should_fallback(exc):
                        logger.info("Triggering fallback to next model in chain")
                        continue
                    else:
                        # Non-retriable error, fail immediately
                        logger.warning("Non-retriable error, aborting fallback chain")
                        raise

        # All models failed
        if last_exception:
            raise LLMCallError(
                f"All models in fallback chain failed. Primary: {model}, "
                f"Chain: {models_to_try}. Last error: {last_exception}"
            ) from last_exception
        else:
            raise LLMCallError(
                f"No suitable models found. Primary: {model}, "
                f"Constraints: max_cost_usd={max_cost_usd}, min_quality={min_quality}"
            )


# ── Singleton instance ─────────────────────────────────────────────────────────
_fallback_policy: LLMFallbackPolicy | None = None


def get_fallback_policy() -> LLMFallbackPolicy:
    """Get or create singleton fallback policy instance."""
    global _fallback_policy
    if _fallback_policy is None:
        _fallback_policy = LLMFallbackPolicy()
    return _fallback_policy


def reset_fallback_policy() -> None:
    """Reset singleton (useful for tests)."""
    global _fallback_policy
    _fallback_policy = None
