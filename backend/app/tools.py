from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Awaitable, Callable

import httpx

from app.config import Settings
from app.models import AgentMessage, AgentTask
from app.repositories import StateRepository


ToolCallable = Callable[..., Awaitable[Any]]


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolCallable] = {}

    def register(self, name: str, tool: ToolCallable) -> None:
        self._tools[name] = tool

    async def execute(self, name: str, **kwargs: Any) -> Any:
        try:
            tool = self._tools[name]
        except KeyError as exc:
            raise ValueError(f"Unknown tool: {name}") from exc
        return await tool(**kwargs)

    @property
    def names(self) -> set[str]:
        return set(self._tools)


class StateTools:
    def __init__(self, repository: StateRepository):
        self.repository = repository

    async def read_whiteboard(self, session_id: str) -> dict[str, Any]:
        state = await self.repository.get_session(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        return state.whiteboard.model_dump(mode="json")

    async def update_whiteboard(
        self, session_id: str, whiteboard: dict[str, Any]
    ) -> dict[str, bool]:
        state = await self.repository.get_session(session_id)
        if not state:
            raise ValueError(f"Session {session_id} not found")
        state.whiteboard = state.whiteboard.model_validate(whiteboard)
        state.whiteboard.revision += 1
        await self.repository.save_session(state)
        return {"success": True}

    async def create_task(self, task: dict[str, Any]) -> dict[str, Any]:
        created = await self.repository.create_task(AgentTask.model_validate(task))
        return created.model_dump(mode="json")

    async def update_task(
        self, task_id: str, updates: dict[str, Any]
    ) -> dict[str, Any] | None:
        task = await self.repository.update_task(task_id, updates)
        return task.model_dump(mode="json") if task else None

    async def read_task(self, task_id: str) -> dict[str, Any] | None:
        task = await self.repository.get_task(task_id)
        return task.model_dump(mode="json") if task else None

    async def send_message(self, message: dict[str, Any]) -> dict[str, Any]:
        created = await self.repository.add_message(
            AgentMessage.model_validate(message)
        )
        return created.model_dump(mode="json")

    async def get_unread_messages(
        self, session_id: str, recipient: str
    ) -> list[dict[str, Any]]:
        messages = await self.repository.unread_messages(session_id, recipient)
        return [message.model_dump(mode="json") for message in messages]


class DebugTools:
    def __init__(self, settings: Settings):
        self.timeout = settings.command_timeout_seconds

    async def _run(self, *args: str) -> dict[str, Any]:
        try:
            process = await asyncio.create_subprocess_exec(
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(
                process.communicate(), timeout=self.timeout
            )
        except TimeoutError:
            process.kill()
            await process.wait()
            return {"success": False, "error": "command timed out"}
        return {
            "success": process.returncode == 0,
            "returncode": process.returncode,
            "output": stdout.decode(errors="replace"),
            "error": stderr.decode(errors="replace"),
        }

    async def grep(
        self, pattern: str, file_path: str, max_matches: int = 200
    ) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            return {"success": False, "error": f"File not found: {file_path}"}
        return await self._run(
            "grep", "-i", "-m", str(max_matches), "--", pattern, str(path)
        )

    async def tail(self, file_path: str, lines: int = 100) -> dict[str, Any]:
        path = Path(file_path)
        if not path.is_file():
            return {"success": False, "error": f"File not found: {file_path}"}
        return await self._run("tail", "-n", str(min(lines, 5000)), "--", str(path))

    async def journalctl(self, unit: str, lines: int = 100) -> dict[str, Any]:
        return await self._run(
            "journalctl",
            "-u",
            unit,
            "-n",
            str(min(lines, 5000)),
            "--no-pager",
        )


class KafkaTools:
    def __init__(self, settings: Settings):
        self.timeout = settings.http_timeout_seconds

    async def _request(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.request(method, url, **kwargs)
            response.raise_for_status()
            if not response.content:
                return {"status_code": response.status_code}
            return response.json()

    async def connector_status(
        self, connect_url: str, connector_name: str
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            f"{connect_url.rstrip('/')}/connectors/{connector_name}/status",
        )

    async def create_connector(
        self, connect_url: str, connector_config: dict[str, Any]
    ) -> dict[str, Any]:
        name = connector_config.get("name")
        config = connector_config.get("config", connector_config)
        if not name:
            raise ValueError("Connector config requires a name")
        return await self._request(
            "PUT",
            f"{connect_url.rstrip('/')}/connectors/{name}/config",
            json=config,
        )

    async def restart_connector(
        self, connect_url: str, connector_name: str
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            f"{connect_url.rstrip('/')}/connectors/{connector_name}/restart",
        )

    async def execute_ksql(
        self, ksqldb_url: str, statement: str
    ) -> dict[str, Any] | list[Any]:
        return await self._request(
            "POST",
            f"{ksqldb_url.rstrip('/')}/ksql",
            json={"ksql": statement, "streamsProperties": {}},
        )

    async def query_ksql(self, ksqldb_url: str, statement: str) -> list[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{ksqldb_url.rstrip('/')}/query-stream",
                json={"sql": statement, "properties": {}},
            )
            response.raise_for_status()
            rows = []
            for line in response.text.splitlines():
                if line.strip():
                    rows.append(json.loads(line))
            return rows

    async def topic_offsets(self, bootstrap_servers: str, topic: str) -> dict[str, Any]:
        process = await asyncio.create_subprocess_exec(
            "kafka-get-offsets.sh",
            "--bootstrap-server",
            bootstrap_servers,
            "--topic",
            topic,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            return {
                "success": False,
                "count": None,
                "error": stderr.decode(errors="replace"),
            }
        offsets = []
        for line in stdout.decode().splitlines():
            parts = line.rsplit(":", 1)
            if len(parts) == 2:
                offsets.append(int(parts[1]))
        return {"success": True, "count": sum(offsets), "offsets": offsets}


def create_tool_registry(
    repository: StateRepository, settings: Settings
) -> ToolRegistry:
    registry = ToolRegistry()
    state = StateTools(repository)
    debug = DebugTools(settings)
    kafka = KafkaTools(settings)
    for name in (
        "read_whiteboard",
        "update_whiteboard",
        "create_task",
        "update_task",
        "read_task",
        "send_message",
        "get_unread_messages",
    ):
        registry.register(name, getattr(state, name))
    for name in ("grep", "tail", "journalctl"):
        registry.register(name, getattr(debug, name))
    for name in (
        "connector_status",
        "create_connector",
        "restart_connector",
        "execute_ksql",
        "query_ksql",
        "topic_offsets",
    ):
        registry.register(name, getattr(kafka, name))
    return registry
