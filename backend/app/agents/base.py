from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.artifact_writer import ArtifactWriter
from app.llm import LLMRouter
from app.models import AgentModelConfig, AgentTask, Artifact, PlannerResponse, WorkerResponse
from app.tools import ToolRegistry


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        model_config: AgentModelConfig,
        llm: LLMRouter,
        tools: ToolRegistry,
    ):
        self.name = name
        self.model_config = model_config
        self.llm = llm
        self.tools = tools

    async def ask_json(self, system_prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        return await self.llm.generate_json(
            self.model_config, system_prompt, json.dumps(payload, default=str)
        )

    @abstractmethod
    async def run(self, task: AgentTask) -> dict[str, Any]: ...


class PlannerAgent(BaseAgent):
    """The only agent with a conversation with the user, a persisted plan, and
    authority to dispatch tasks / commit artifacts to disk. Concrete system prompt
    is set by app.agents.PlannerAgent."""

    system_prompt: str = ""

    async def run(self, task: AgentTask) -> dict[str, Any]:
        raw = await self.ask_json(self.system_prompt, task.context)
        return PlannerResponse.model_validate(raw).model_dump(mode="json")

    async def commit_artifact(
        self, artifact: Artifact, session_id: str, deployment_root: Path
    ) -> Artifact:
        """Pure code, no LLM call — the artifact was already generated and
        approved; this just persists it."""
        return ArtifactWriter.commit(artifact, session_id, deployment_root)


class WorkerAgent(BaseAgent):
    """Stateless per call. Default path implements generate(); run() wraps it.
    Tool-calling agents (Executor, Debug) override run() directly instead."""

    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raise NotImplementedError(f"{type(self).__name__} must implement generate()")

    async def run(self, task: AgentTask) -> dict[str, Any]:
        response = await self.generate(task.context)
        return response.model_dump(mode="json")
