from __future__ import annotations

import json
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from app.artifact_writer import ArtifactWriter
from app.llm import LLMRouter, ToolExecutor
from app.models import AgentModelConfig, AgentTask, Artifact, PlannerResponse, WorkerResponse
from app.tools import ToolRegistry

# The Planner's only tool: fetch chat history beyond the last-10-plus-starred
# window it's normally given, when it suspects something relevant was said
# earlier. Only exercised on providers with real function-calling support
# (see LLMClient.generate_json_with_tools) — on others it's simply unused.
QUERY_MESSAGES_TOOL: dict[str, Any] = {
    "type": "function",
    "name": "query_messages",
    "description": (
        "Search or fetch this session's full human<->planner chat history, beyond "
        "the last 10 messages (plus any starred ones) already given to you in "
        "conversation_history. Use this when you suspect something relevant to the "
        "pipeline was said earlier in the conversation that isn't in your current "
        "context."
    ),
    "parameters": {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": (
                    "Optional substring to filter messages by content. "
                    "Omit to get the full history."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
}


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

    async def ask_json_with_tools(
        self,
        system_prompt: str,
        payload: dict[str, Any],
        tools: list[dict[str, Any]],
        tool_executor: ToolExecutor,
    ) -> dict[str, Any]:
        return await self.llm.generate_json_with_tools(
            self.model_config, system_prompt, json.dumps(payload, default=str), tools, tool_executor
        )

    @abstractmethod
    async def run(self, task: AgentTask) -> dict[str, Any]: ...


class PlannerAgent(BaseAgent):
    """The only agent with a conversation with the user, a persisted plan, and
    authority to dispatch tasks / commit artifacts to disk. Concrete system prompt
    is set by app.agents.PlannerAgent."""

    system_prompt: str = ""

    async def run(self, task: AgentTask) -> dict[str, Any]:
        async def tool_executor(name: str, arguments: dict[str, Any]) -> Any:
            if name != "query_messages":
                raise ValueError(f"Planner cannot call tool: {name}")
            return await self.tools.execute(
                "query_messages", session_id=task.session_id, query=arguments.get("query")
            )

        raw = await self.ask_json_with_tools(
            self.system_prompt, task.context, [QUERY_MESSAGES_TOOL], tool_executor
        )
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
