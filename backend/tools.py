from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

import httpx
from bson import ObjectId
from mongo import (
    context_messages,
    messages,
    pipeline_sessions,
    tasks,
)

# ==========================================================
# BASE TOOL
# ==========================================================


class Tool(ABC):
    name: str
    description: str

    @abstractmethod
    async def execute(self, **kwargs) -> Any:
        pass


# ==========================================================
# TOOL REGISTRY
# ==========================================================


class ToolRegistry:
    def __init__(self):
        self.tools: Dict[str, Tool] = {}

    def register(self, tool: Tool):
        self.tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        return self.tools[name]

    async def execute(
        self,
        name: str,
        **kwargs,
    ):
        tool = self.get(name)
        return await tool.execute(**kwargs)


# ==========================================================
# WHITEBOARD TOOLS
# ==========================================================


class ReadWhiteboardTool(Tool):
    name = "read_whiteboard"
    description = "Read session whiteboard"

    async def execute(
        self,
        session_id: str,
    ):

        doc = pipeline_sessions.find_one({"session_id": session_id})

        if not doc:
            raise ValueError(f"Session {session_id} not found")

        return doc["whiteboard"]


class UpdateWhiteboardTool(Tool):
    name = "update_whiteboard"
    description = "Update session whiteboard"

    async def execute(
        self,
        session_id: str,
        whiteboard: dict,
    ):

        pipeline_sessions.update_one(
            {"session_id": session_id}, {"$set": {"whiteboard": whiteboard}}
        )

        return {"success": True}


# ==========================================================
# TASK TOOLS
# ==========================================================


class CreateTaskTool(Tool):
    name = "create_task"

    async def execute(
        self,
        task: dict,
    ):

        tasks.insert_one(task)

        return {
            "success": True,
            "task_id": task["task_id"],
        }


class ReadTaskTool(Tool):
    name = "read_task"

    async def execute(
        self,
        task_id: str,
    ):

        task = tasks.find_one({"task_id": task_id})

        return task


class UpdateTaskTool(Tool):
    name = "update_task"

    async def execute(
        self,
        task_id: str,
        updates: dict,
    ):

        tasks.update_one({"task_id": task_id}, {"$set": updates})

        return {"success": True}


# ==========================================================
# MESSAGE TOOLS
# ==========================================================


class SendMessageTool(Tool):
    name = "send_message"

    async def execute(
        self,
        message: dict,
    ):

        messages.insert_one(message)

        return {"success": True}


class GetUnreadMessagesTool(Tool):
    name = "get_unread_messages"

    async def execute(
        self,
        session_id: str,
    ):

        result = list(
            messages.find(
                {
                    "session_id": session_id,
                    "read": False,
                }
            )
        )

        return result


class MarkMessageReadTool(Tool):
    name = "mark_message_read"

    async def execute(
        self,
        message_id: str,
    ):

        messages.update_one({"message_id": message_id}, {"$set": {"read": True}})

        return {"success": True}


# ==========================================================
# CONTEXT TOOLS
# ==========================================================


class AddContextTool(Tool):
    name = "add_context"

    async def execute(
        self,
        context: dict,
    ):

        context_messages.insert_one(context)

        return {"success": True}


class ReadContextTool(Tool):
    name = "read_context"

    async def execute(
        self,
        task_id: str,
    ):

        return list(context_messages.find({"task_id": task_id}))


# ==========================================================
# LOG TOOLS
# ==========================================================


class TailTool(Tool):
    name = "tail"

    async def execute(
        self,
        file_path: str,
        lines: int = 100,
    ):

        process = await asyncio.create_subprocess_exec(
            "tail",
            "-n",
            str(lines),
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "output": stdout.decode(),
            "error": stderr.decode(),
        }


class GrepTool(Tool):
    name = "grep"

    async def execute(
        self,
        pattern: str,
        file_path: str,
    ):

        process = await asyncio.create_subprocess_exec(
            "grep",
            "-i",
            pattern,
            file_path,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": True,
            "matches": stdout.decode(),
            "error": stderr.decode(),
        }


class JournalctlTool(Tool):
    name = "journalctl"

    async def execute(
        self,
        unit: str,
        lines: int = 100,
    ):

        process = await asyncio.create_subprocess_exec(
            "journalctl",
            "-u",
            unit,
            "-n",
            str(lines),
            "--no-pager",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        stdout, stderr = await process.communicate()

        return {
            "success": process.returncode == 0,
            "output": stdout.decode(),
            "error": stderr.decode(),
        }


# ==========================================================
# CONNECT TOOLS
# ==========================================================


class ConnectorStatusTool(Tool):
    name = "connector_status"

    async def execute(
        self,
        connect_url: str,
        connector_name: str,
    ):

        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{connect_url}/connectors/{connector_name}/status"
            )

            response.raise_for_status()

            return response.json()


class CreateConnectorTool(Tool):
    name = "create_connector"

    async def execute(
        self,
        connect_url: str,
        connector_config: dict,
    ):

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{connect_url}/connectors",
                json=connector_config,
            )

            response.raise_for_status()

            return response.json()


class RestartConnectorTool(Tool):
    name = "restart_connector"

    async def execute(
        self,
        connect_url: str,
        connector_name: str,
    ):

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{connect_url}/connectors/{connector_name}/restart"
            )

            return {"status": response.status_code}


# ==========================================================
# KSQLDB TOOLS
# ==========================================================


class ExecuteKsqlTool(Tool):
    name = "execute_ksql"

    async def execute(
        self,
        ksqldb_url: str,
        statement: str,
    ):

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{ksqldb_url}/ksql",
                json={"ksql": statement},
            )

            response.raise_for_status()

            return response.json()


# ==========================================================
# TOOL FACTORY
# ==========================================================


def create_tool_registry():

    registry = ToolRegistry()

    registry.register(ReadWhiteboardTool())

    registry.register(UpdateWhiteboardTool())

    registry.register(CreateTaskTool())

    registry.register(ReadTaskTool())

    registry.register(UpdateTaskTool())

    registry.register(SendMessageTool())

    registry.register(GetUnreadMessagesTool())

    registry.register(MarkMessageReadTool())

    registry.register(AddContextTool())

    registry.register(ReadContextTool())

    registry.register(TailTool())

    registry.register(GrepTool())

    registry.register(JournalctlTool())

    registry.register(ConnectorStatusTool())

    registry.register(CreateConnectorTool())

    registry.register(RestartConnectorTool())

    registry.register(ExecuteKsqlTool())

    return registry
