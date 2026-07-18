from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from app.agents import BaseAgent, build_agents
from app.llm import LLMRouter
from app.models import (
    AgentMessage,
    AgentTask,
    EventType,
    SessionEvent,
    SessionState,
    TaskStatus,
)
from app.repositories import StateRepository
from app.tools import ToolRegistry


@dataclass
class QueuedTask:
    task: AgentTask
    future: asyncio.Future[AgentTask]


@dataclass
class QueuedEvent:
    event: SessionEvent
    future: asyncio.Future[None]


class SessionRuntime:
    def __init__(
        self,
        state: SessionState,
        repository: StateRepository,
        agents: dict[str, BaseAgent],
    ):
        self.session_id = state.session_id
        self.repository = repository
        self.agents = agents
        self.task_queue: asyncio.Queue[QueuedTask | None] = asyncio.Queue()
        self.event_queue: asyncio.Queue[QueuedEvent | None] = asyncio.Queue()
        self.worker = asyncio.create_task(self._run_tasks())
        self.event_worker = asyncio.create_task(self._run_events())

    async def submit(
        self, agent: str, instruction: str, context: dict[str, Any]
    ) -> AgentTask:
        if agent not in self.agents:
            raise ValueError(f"Unknown agent: {agent}")
        task = AgentTask(
            session_id=self.session_id,
            agent=agent,
            instruction=instruction,
            context=context,
        )
        await self.repository.create_task(task)
        await self.emit(
            EventType.TASK,
            "runtime",
            {"task_id": task.task_id, "agent": agent, "status": "pending"},
        )
        future: asyncio.Future[AgentTask] = asyncio.get_running_loop().create_future()
        await self.task_queue.put(QueuedTask(task=task, future=future))
        return await future

    async def emit(
        self, event_type: EventType, source: str, data: dict[str, Any]
    ) -> None:
        future: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        await self.event_queue.put(
            QueuedEvent(
                event=SessionEvent(
                    session_id=self.session_id,
                    type=event_type,
                    source=source,
                    data=data,
                ),
                future=future,
            )
        )
        await future

    async def close(self) -> None:
        await self.task_queue.put(None)
        await self.event_queue.put(None)
        await asyncio.gather(self.worker, self.event_worker, return_exceptions=True)

    async def _run_tasks(self) -> None:
        while queued := await self.task_queue.get():
            task = queued.task
            try:
                task = (
                    await self.repository.update_task(
                        task.task_id, {"status": TaskStatus.IN_PROGRESS}
                    )
                    or task
                )
                result = await self.agents[task.agent].run(task)
                completed = await self.repository.update_task(
                    task.task_id,
                    {"status": TaskStatus.COMPLETED, "result": result},
                )
                assert completed is not None
                await self.repository.add_message(
                    AgentMessage(
                        session_id=self.session_id,
                        sender=task.agent,
                        recipient="planner",
                        content={"task_id": task.task_id, "result": result},
                    )
                )
                await self.emit(
                    EventType.TASK,
                    task.agent,
                    {
                        "task_id": task.task_id,
                        "agent": task.agent,
                        "status": "completed",
                    },
                )
                queued.future.set_result(completed)
            except Exception as exc:
                failed = await self.repository.update_task(
                    task.task_id,
                    {"status": TaskStatus.FAILED, "error": str(exc)},
                )
                await self.emit(
                    EventType.ERROR,
                    task.agent,
                    {"task_id": task.task_id, "error": str(exc)},
                )
                if failed:
                    queued.future.set_result(failed)
                else:
                    queued.future.set_exception(exc)
            finally:
                self.task_queue.task_done()

    async def _run_events(self) -> None:
        while queued := await self.event_queue.get():
            try:
                await self.repository.add_event(queued.event)
                queued.future.set_result(None)
            except Exception as exc:
                queued.future.set_exception(exc)
            finally:
                self.event_queue.task_done()


class RuntimeManager:
    def __init__(
        self,
        repository: StateRepository,
        llm: LLMRouter,
        tools: ToolRegistry,
    ):
        self.repository = repository
        self.llm = llm
        self.tools = tools
        self._runtimes: dict[str, SessionRuntime] = {}
        self._lock = asyncio.Lock()

    async def get(self, state: SessionState) -> SessionRuntime:
        async with self._lock:
            runtime = self._runtimes.get(state.session_id)
            if runtime is None:
                runtime = SessionRuntime(
                    state,
                    self.repository,
                    build_agents(state.config, self.llm, self.tools),
                )
                self._runtimes[state.session_id] = runtime
            return runtime

    async def close(self) -> None:
        runtimes = list(self._runtimes.values())
        self._runtimes.clear()
        await asyncio.gather(
            *(runtime.close() for runtime in runtimes), return_exceptions=True
        )
