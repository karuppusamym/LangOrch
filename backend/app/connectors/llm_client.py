"""LLM client connector (OpenAI-compatible chat completions API)."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.config import settings

logger = logging.getLogger("langorch.connectors.llm")


class LLMClient:
    def __init__(self):
        self.base_url = settings.LLM_BASE_URL.rstrip("/")
        self.api_key = settings.LLM_API_KEY
        self.timeout = settings.LLM_TIMEOUT_SECONDS

    def complete(
        self,
        prompt: str,
        model: str,
        temperature: float = 0.7,
        max_tokens: int | None = None,
        system_prompt: str | None = None,
        json_mode: bool = False,
    ) -> dict[str, Any]:
        if not self.api_key:
            raise LLMCallError("LLM_API_KEY is not configured")

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
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
        logger.info("LLM call: model=%s", model)

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
            return {
                "text": text,
                "raw": data,
            }
        except httpx.HTTPStatusError as exc:
            raise LLMCallError(f"HTTP {exc.response.status_code}") from exc
        except httpx.RequestError as exc:
            raise LLMCallError(str(exc)) from exc
        except Exception as exc:
            if isinstance(exc, LLMCallError):
                raise
            raise LLMCallError(str(exc)) from exc


class LLMCallError(Exception):
    pass
