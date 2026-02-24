"""LLM client connector (OpenAI-compatible chat completions API).

Supports dynamic per-call overrides for base_url, api_key, and extra_headers
to enable API gateway integration, multi-provider routing, and tenant isolation.

Circuit breaker: after ``_LLM_CIRCUIT_THRESHOLD`` consecutive failures the
client short-circuits with ``LLMCallError`` until ``_LLM_CIRCUIT_RESET_SECONDS``
have elapsed, preventing cascading failures against an unhealthy LLM endpoint.
"""

from __future__ import annotations

import json as _json
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("langorch.connectors.llm")

# ── Circuit breaker state (module-level, process-scoped) ──────────────────────
_llm_consecutive_failures: int = 0
_llm_circuit_open_at: datetime | None = None
_LLM_CIRCUIT_THRESHOLD: int = 5
_LLM_CIRCUIT_RESET_SECONDS: int = 300


def _check_llm_circuit() -> None:
    """Raise immediately if the LLM circuit breaker is open."""
    global _llm_circuit_open_at
    if _llm_circuit_open_at is None:
        return
    elapsed = (datetime.now(timezone.utc) - _llm_circuit_open_at).total_seconds()
    if elapsed < _LLM_CIRCUIT_RESET_SECONDS:
        raise LLMCallError(
            f"LLM circuit breaker open (failed {_LLM_CIRCUIT_THRESHOLD}× "
            f"consecutively; resets in {_LLM_CIRCUIT_RESET_SECONDS - int(elapsed)}s)"
        )
    # Reset period elapsed — close the circuit
    _llm_circuit_open_at = None


def _record_llm_success() -> None:
    global _llm_consecutive_failures, _llm_circuit_open_at
    _llm_consecutive_failures = 0
    _llm_circuit_open_at = None


def _record_llm_failure() -> None:
    global _llm_consecutive_failures, _llm_circuit_open_at
    _llm_consecutive_failures += 1
    if _llm_consecutive_failures >= _LLM_CIRCUIT_THRESHOLD:
        _llm_circuit_open_at = datetime.now(timezone.utc)
        logger.warning(
            "LLM circuit breaker OPENED after %d consecutive failures",
            _llm_consecutive_failures,
        )


def reset_llm_circuit_breaker() -> None:
    """Reset LLM circuit breaker state (useful for tests)."""
    global _llm_consecutive_failures, _llm_circuit_open_at
    _llm_consecutive_failures = 0
    _llm_circuit_open_at = None


class LLMClient:
    """OpenAI-compatible chat completion client with gateway header support.

    Parameters
    ----------
    base_url : str | None
        Override the global ``LLM_BASE_URL`` for this client instance.
    api_key : str | None
        Override the global ``LLM_API_KEY``.
    extra_headers : dict[str, str] | None
        Additional HTTP headers merged on every request (e.g. gateway auth).
        These are merged *on top of* the global ``LLM_GATEWAY_HEADERS``.
    """

    def __init__(
        self,
        base_url: str | None = None,
        api_key: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ):
        self.base_url = (base_url or settings.LLM_BASE_URL).rstrip("/")
        self.api_key = api_key or settings.LLM_API_KEY
        self.timeout = settings.LLM_TIMEOUT_SECONDS

        # Merge gateway headers from config + per-call overrides
        self._extra_headers: dict[str, str] = {}
        if settings.LLM_GATEWAY_HEADERS:
            try:
                parsed = _json.loads(settings.LLM_GATEWAY_HEADERS)
                if isinstance(parsed, dict):
                    self._extra_headers.update(parsed)
            except (_json.JSONDecodeError, TypeError):
                logger.warning("LLM_GATEWAY_HEADERS is not valid JSON — ignored")
        if extra_headers:
            self._extra_headers.update(extra_headers)

    def complete(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        # Circuit breaker pre-check
        _check_llm_circuit()

        if not self.api_key:
            raise LLMCallError("LLM_API_KEY is not configured")

        headers: dict[str, str] = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        # Merge extra headers (gateway headers + per-call overrides)
        headers.update(self._extra_headers)

        messages: list[dict[str, Any]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        messages.append({"role": "user", "content": prompt})
        body: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "temperature": temperature,
        }
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        url = f"{self.base_url}/chat/completions"
        logger.info("LLM call: model=%s url=%s", model, url)

        try:
            with httpx.Client(timeout=self.timeout, headers=headers) as client:
                resp = client.post(url, json=body)
                resp.raise_for_status()
                data = resp.json()

            choices = data.get("choices") or []
            if not choices:
                raise LLMCallError("LLM response missing choices")

            message = choices[0].get("message", {})
            text = message.get("content", "")
            usage = data.get("usage") or {}

            _record_llm_success()

            return {
                "text": text,
                "raw": data,
                "usage": {
                    "prompt_tokens": usage.get("prompt_tokens", 0),
                    "completion_tokens": usage.get("completion_tokens", 0),
                    "total_tokens": usage.get("total_tokens", 0),
                    "model": data.get("model", ""),
                },
            }
        except httpx.HTTPStatusError as exc:
            _record_llm_failure()
            raise LLMCallError(f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            _record_llm_failure()
            raise LLMCallError(str(exc)) from exc
        except Exception as exc:
            if isinstance(exc, LLMCallError):
                _record_llm_failure()
                raise
            _record_llm_failure()
            raise LLMCallError(str(exc)) from exc


class LLMCallError(Exception):
    pass
