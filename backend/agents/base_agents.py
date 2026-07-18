from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from llm import LLMClient, LLMFactory
from models import (
    AgentModelConfig,
    AgentTask,
)
from tools import ToolRegistry


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        llm: LLMClient,
        tools: ToolRegistry,
    ):
        self.name = name
        self.llm = llm
        self.tools = tools

    async def complete_task(
        self,
        task_id: str,
        result: dict,
        result_status: str = "ok",
    ):

        await self.tools.execute(
            "update_task",
            task_id=task_id,
            updates={
                "status": "completed",
                "result": result,
                "result_status": result_status,
            },
        )

    async def fail_task(
        self,
        task_id: str,
        reason: str,
    ):

        await self.tools.execute(
            "update_task",
            task_id=task_id,
            updates={
                "status": "failed",
                "result_status": "failed",
                "notes": reason,
            },
        )

    async def send_message(
        self,
        message: dict,
    ):

        await self.tools.execute(
            "send_message",
            message=message,
        )

    async def read_task(
        self,
        task_id: str,
    ):

        return await self.tools.execute(
            "read_task",
            task_id=task_id,
        )

    async def read_context(
        self,
        task_id: str,
    ):

        return await self.tools.execute(
            "read_context",
            task_id=task_id,
        )

    @abstractmethod
    async def run(
        self,
        task: AgentTask,
    ):
        pass


class ThinkingAgent(BaseAgent):
    async def read_whiteboard(
        self,
        session_id: str,
    ):

        return await self.tools.execute(
            "read_whiteboard",
            session_id=session_id,
        )

    async def update_whiteboard(
        self,
        session_id: str,
        whiteboard: dict,
    ):

        return await self.tools.execute(
            "update_whiteboard",
            session_id=session_id,
            whiteboard=whiteboard,
        )

    async def create_task(
        self,
        task: dict,
    ):

        return await self.tools.execute(
            "create_task",
            task=task,
        )


class ServiceAgent(BaseAgent):
    """
    Execution-oriented agents.

    Connect
    KSQL
    Executor
    Debug
    """

    pass


class AgentFactory:
    @staticmethod
    def build(
        agent_cls,
        config: AgentModelConfig,
        tools: ToolRegistry,
        name: str,
    ):

        return agent_cls(
            name=name,
            llm=LLMFactory.create(config),
            tools=tools,
        )
