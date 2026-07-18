from __future__ import annotations

import json
import os
from abc import ABC, abstractmethod
from typing import Any, Dict, Optional

import httpx
from models import AgentModelConfig
from openai import AsyncOpenAI

# ==========================================================
# BASE CLIENT
# ==========================================================


class LLMClient(ABC):
    """
    Base abstraction used by every agent.

    Planner
    Evaluator
    EdgeCase
    Connect
    KsqlDB
    Executor
    Debug

    should never know which provider
    they're talking to.
    """

    def __init__(self, config: AgentModelConfig):
        self.config = config

    @abstractmethod
    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:
        pass


# ==========================================================
# OPENAI
# ==========================================================


class OpenAIClient(LLMClient):
    """
    Uses OpenAI Responses API.
    """

    def __init__(self, config: AgentModelConfig):
        super().__init__(config)

        self.client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:

        response = await self.client.responses.create(
            model=self.config.model,
            temperature=self.config.temperature,
            max_output_tokens=self.config.max_tokens,
            instructions=system_prompt,
            input=user_prompt,
        )

        return response.output_text


# ==========================================================
# OLLAMA
# ==========================================================


class OllamaClient(LLMClient):
    """
    Async Ollama HTTP API client.
    """

    def __init__(self, config: AgentModelConfig):
        super().__init__(config)

        self.base_url = os.getenv("OLLAMA_URL", "http://localhost:11434")

    async def generate(
        self,
        system_prompt: str,
        user_prompt: str,
        json_mode: bool = False,
    ) -> str:

        payload: Dict[str, Any] = {
            "model": self.config.model,
            "stream": False,
            "messages": [
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": user_prompt,
                },
            ],
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_tokens,
            },
        }

        if json_mode:
            payload["format"] = "json"

        async with httpx.AsyncClient(timeout=300) as client:
            response = await client.post(
                f"{self.base_url}/api/chat",
                json=payload,
            )

            response.raise_for_status()

            data = response.json()

            return data["message"]["content"]


# ==========================================================
# FACTORY
# ==========================================================


class LLMFactory:
    @staticmethod
    def create(
        config: AgentModelConfig,
    ) -> LLMClient:

        if config.backend == "openai":
            return OpenAIClient(config)

        if config.backend == "ollama":
            return OllamaClient(config)

        raise ValueError(f"Unsupported backend: {config.backend}")


# ==========================================================
# HELPERS
# ==========================================================


async def generate_json(
    client: LLMClient,
    system_prompt: str,
    user_prompt: str,
) -> Dict[str, Any]:
    """
    Utility for agents expecting JSON output.
    """

    response = await client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=True,
    )

    try:
        return json.loads(response)

    except Exception as e:
        raise ValueError(f"Invalid JSON returned by model: {e}")


async def generate_text(
    client: LLMClient,
    system_prompt: str,
    user_prompt: str,
) -> str:

    return await client.generate(
        system_prompt=system_prompt,
        user_prompt=user_prompt,
        json_mode=False,
    )
