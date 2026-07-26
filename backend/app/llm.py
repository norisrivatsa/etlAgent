from __future__ import annotations

import json
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

import httpx
from openai import AsyncOpenAI

from app.config import Settings
from app.models import AgentModelConfig, ModelProvider


class LLMError(RuntimeError):
    pass


class LLMClient(ABC):
    @abstractmethod
    async def generate_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]: ...


def _parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.removeprefix("```json").removeprefix("```")
        cleaned = cleaned.removesuffix("```").strip()
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise LLMError(f"Model returned invalid JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise LLMError("Model response must be a JSON object")
    return value


class OpenAILLMClient(LLMClient):
    def __init__(self, settings: Settings):
        if not settings.openai_api_key:
            raise LLMError(
                "OpenAI provider requires OPENAI_API_KEY or openai_api_key to be set"
            )
        self.client = AsyncOpenAI(api_key=settings.openai_api_key)

    async def generate_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        is_reasoning_model = config.model.startswith(("gpt-5", "o1", "o3", "o4"))
        max_output_tokens = config.max_tokens
        if is_reasoning_model:
            # Reasoning models spend part of max_output_tokens on invisible reasoning
            # tokens before any visible completion text — without a generous floor,
            # verbose JSON (e.g. KsqlDBAgent's multi-statement pipeline) gets silently
            # truncated mid-string well below the nominal budget.
            max_output_tokens = max(config.max_tokens, 8192)
        kwargs: dict[str, Any] = {
            "model": config.model,
            "instructions": system_prompt,
            # text.format=json_object requires the word "json" to appear in the input
            # itself (not just instructions) — user_prompt is a raw JSON payload with no
            # such literal word in it, so the API rejects it without this preamble.
            "input": f"Respond with a single JSON object per the instructions. Input JSON:\n{user_prompt}",
            "max_output_tokens": max_output_tokens,
            "text": {"format": {"type": "json_object"}},
        }
        # Reasoning models (gpt-5/o-series) don't support sampling temperature at all —
        # the Responses API rejects the param outright rather than ignoring it.
        if not is_reasoning_model:
            kwargs["temperature"] = config.temperature
        try:
            response = await self.client.responses.create(**kwargs)
        except Exception as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc
        return _parse_json(response.output_text)


class OllamaLLMClient(LLMClient):
    def __init__(self, settings: Settings):
        self.base_url = settings.ollama_url.rstrip("/")
        self.timeout = settings.http_timeout_seconds

    async def generate_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        payload = {
            "model": config.model,
            "stream": False,
            "format": "json",
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "options": {
                "temperature": config.temperature,
                "num_predict": config.max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(f"{self.base_url}/api/chat", json=payload)
                response.raise_for_status()
        except httpx.ConnectError as exc:
            raise LLMError(
                "Ollama is not reachable at "
                f"{self.base_url}. Start it with `ollama serve`, or set OLLAMA_URL "
                "to the URL where Ollama is running."
            ) from exc
        except httpx.TimeoutException as exc:
            raise LLMError(
                f"Ollama request timed out at {self.base_url} after "
                f"{self.timeout} seconds. Increase HTTP_TIMEOUT_SECONDS if this "
                "model needs more time."
            ) from exc
        except httpx.HTTPStatusError as exc:
            detail = exc.response.text.strip()
            if exc.response.status_code in {400, 404}:
                raise LLMError(
                    f"Ollama model `{config.model}` is not available from "
                    f"{self.base_url}. Pull it with `ollama pull {config.model}`."
                    + (f" Ollama response: {detail}" if detail else "")
                ) from exc
            raise LLMError(
                f"Ollama request failed with HTTP {exc.response.status_code}."
                + (f" Ollama response: {detail}" if detail else "")
            ) from exc
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        try:
            content = response.json()["message"]["content"]
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise LLMError("Ollama returned an unexpected response shape") from exc
        return _parse_json(content)


class LLMRouter:
    def __init__(self, settings: Settings):
        self.client_factories: dict[ModelProvider, Callable[[], LLMClient]] = {
            ModelProvider.OPENAI: lambda: OpenAILLMClient(settings),
            ModelProvider.OLLAMA: lambda: OllamaLLMClient(settings),
        }
        self.clients: dict[ModelProvider, LLMClient] = {}

    async def generate_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        client = self.clients.get(config.provider)
        if client is None:
            client = self.client_factories[config.provider]()
            self.clients[config.provider] = client
        return await client.generate_json(config, system_prompt, user_prompt)


class StubLLMRouter:
    """Deterministic injectable LLM used by tests and local examples."""

    def __init__(self, responses: list[dict[str, Any]] | None = None):
        self.responses = responses or []

    async def generate_json(
        self,
        config: AgentModelConfig,
        system_prompt: str,
        user_prompt: str,
    ) -> dict[str, Any]:
        del config, system_prompt, user_prompt
        if not self.responses:
            return {"reply": "Requirements recorded.", "requirements_patch": {}}
        return self.responses.pop(0)
