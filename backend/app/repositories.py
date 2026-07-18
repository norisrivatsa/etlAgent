from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime
from typing import Any, Protocol

from motor.motor_asyncio import AsyncIOMotorDatabase
from pymongo import ASCENDING, ReturnDocument

from app.models import (
    AgentMessage,
    AgentTask,
    SessionEvent,
    SessionState,
    utc_now,
)


class StateRepository(Protocol):
    async def create_session(self, state: SessionState) -> SessionState: ...
    async def list_sessions(self, limit: int = 100) -> list[SessionState]: ...
    async def get_session(self, session_id: str) -> SessionState | None: ...
    async def save_session(self, state: SessionState) -> SessionState: ...
    async def patch_session(
        self, session_id: str, updates: dict[str, Any]
    ) -> SessionState | None: ...
    async def create_task(self, task: AgentTask) -> AgentTask: ...
    async def get_task(self, task_id: str) -> AgentTask | None: ...
    async def update_task(
        self, task_id: str, updates: dict[str, Any]
    ) -> AgentTask | None: ...
    async def add_message(self, message: AgentMessage) -> AgentMessage: ...
    async def unread_messages(
        self, session_id: str, recipient: str
    ) -> list[AgentMessage]: ...
    async def add_event(self, event: SessionEvent) -> SessionEvent: ...
    async def list_events(
        self, session_id: str, after: datetime | None = None, limit: int = 100
    ) -> list[SessionEvent]: ...


def _dump(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="python")


class MongoStateRepository:
    def __init__(self, database: AsyncIOMotorDatabase):
        self.sessions = database.sessions
        self.tasks = database.tasks
        self.messages = database.messages
        self.events = database.events

    async def ensure_indexes(self) -> None:
        await asyncio.gather(
            self.sessions.create_index("session_id", unique=True),
            self.sessions.create_index("updated_at"),
            self.tasks.create_index([("session_id", ASCENDING), ("status", ASCENDING)]),
            self.tasks.create_index("task_id", unique=True),
            self.messages.create_index(
                [
                    ("session_id", ASCENDING),
                    ("recipient", ASCENDING),
                    ("read", ASCENDING),
                ]
            ),
            self.events.create_index(
                [("session_id", ASCENDING), ("created_at", ASCENDING)]
            ),
            self.events.create_index("event_id", unique=True),
        )

    async def create_session(self, state: SessionState) -> SessionState:
        await self.sessions.insert_one(_dump(state))
        return state

    async def list_sessions(self, limit: int = 100) -> list[SessionState]:
        cursor = (
            self.sessions.find({}, {"_id": 0})
            .sort("updated_at", ASCENDING)
            .limit(limit)
        )
        sessions = [SessionState.model_validate(doc) async for doc in cursor]
        return list(reversed(sessions))

    async def get_session(self, session_id: str) -> SessionState | None:
        doc = await self.sessions.find_one({"session_id": session_id}, {"_id": 0})
        return SessionState.model_validate(doc) if doc else None

    async def save_session(self, state: SessionState) -> SessionState:
        state.updated_at = utc_now()
        await self.sessions.replace_one(
            {"session_id": state.session_id}, _dump(state), upsert=False
        )
        return state

    async def patch_session(
        self, session_id: str, updates: dict[str, Any]
    ) -> SessionState | None:
        updates["updated_at"] = utc_now()
        doc = await self.sessions.find_one_and_update(
            {"session_id": session_id},
            {"$set": updates},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        return SessionState.model_validate(doc) if doc else None

    async def create_task(self, task: AgentTask) -> AgentTask:
        await self.tasks.insert_one(_dump(task))
        return task

    async def get_task(self, task_id: str) -> AgentTask | None:
        doc = await self.tasks.find_one({"task_id": task_id}, {"_id": 0})
        return AgentTask.model_validate(doc) if doc else None

    async def update_task(
        self, task_id: str, updates: dict[str, Any]
    ) -> AgentTask | None:
        updates["updated_at"] = utc_now()
        doc = await self.tasks.find_one_and_update(
            {"task_id": task_id},
            {"$set": updates},
            projection={"_id": 0},
            return_document=ReturnDocument.AFTER,
        )
        return AgentTask.model_validate(doc) if doc else None

    async def add_message(self, message: AgentMessage) -> AgentMessage:
        await self.messages.insert_one(_dump(message))
        return message

    async def unread_messages(
        self, session_id: str, recipient: str
    ) -> list[AgentMessage]:
        cursor = self.messages.find(
            {"session_id": session_id, "recipient": recipient, "read": False},
            {"_id": 0},
        ).sort("created_at", ASCENDING)
        docs = await cursor.to_list(length=1000)
        if docs:
            await self.messages.update_many(
                {"message_id": {"$in": [doc["message_id"] for doc in docs]}},
                {"$set": {"read": True}},
            )
        return [AgentMessage.model_validate(doc) for doc in docs]

    async def add_event(self, event: SessionEvent) -> SessionEvent:
        await self.events.insert_one(_dump(event))
        return event

    async def list_events(
        self, session_id: str, after: datetime | None = None, limit: int = 100
    ) -> list[SessionEvent]:
        query: dict[str, Any] = {"session_id": session_id}
        if after:
            query["created_at"] = {"$gt": after}
        cursor = (
            self.events.find(query, {"_id": 0})
            .sort("created_at", ASCENDING)
            .limit(limit)
        )
        return [SessionEvent.model_validate(doc) async for doc in cursor]


class InMemoryStateRepository:
    def __init__(self) -> None:
        self.sessions: dict[str, SessionState] = {}
        self.tasks: dict[str, AgentTask] = {}
        self.messages: list[AgentMessage] = []
        self.events: list[SessionEvent] = []
        self._lock = asyncio.Lock()

    async def create_session(self, state: SessionState) -> SessionState:
        async with self._lock:
            self.sessions[state.session_id] = deepcopy(state)
        return deepcopy(state)

    async def list_sessions(self, limit: int = 100) -> list[SessionState]:
        sessions = sorted(
            self.sessions.values(), key=lambda state: state.updated_at, reverse=True
        )
        return [deepcopy(state) for state in sessions[:limit]]

    async def get_session(self, session_id: str) -> SessionState | None:
        state = self.sessions.get(session_id)
        return deepcopy(state) if state else None

    async def save_session(self, state: SessionState) -> SessionState:
        state.updated_at = utc_now()
        async with self._lock:
            self.sessions[state.session_id] = deepcopy(state)
        return deepcopy(state)

    async def patch_session(
        self, session_id: str, updates: dict[str, Any]
    ) -> SessionState | None:
        state = self.sessions.get(session_id)
        if not state:
            return None
        data = state.model_dump(mode="python")
        for dotted_key, value in updates.items():
            target = data
            parts = dotted_key.split(".")
            for part in parts[:-1]:
                target = target[part]
            target[parts[-1]] = value
        updated = SessionState.model_validate(data)
        updated.updated_at = utc_now()
        return await self.save_session(updated)

    async def create_task(self, task: AgentTask) -> AgentTask:
        self.tasks[task.task_id] = deepcopy(task)
        return deepcopy(task)

    async def get_task(self, task_id: str) -> AgentTask | None:
        task = self.tasks.get(task_id)
        return deepcopy(task) if task else None

    async def update_task(
        self, task_id: str, updates: dict[str, Any]
    ) -> AgentTask | None:
        task = self.tasks.get(task_id)
        if not task:
            return None
        data = task.model_dump(mode="python")
        data.update(updates)
        data["updated_at"] = utc_now()
        updated = AgentTask.model_validate(data)
        self.tasks[task_id] = updated
        return deepcopy(updated)

    async def add_message(self, message: AgentMessage) -> AgentMessage:
        self.messages.append(deepcopy(message))
        return deepcopy(message)

    async def unread_messages(
        self, session_id: str, recipient: str
    ) -> list[AgentMessage]:
        found = []
        for message in self.messages:
            if (
                message.session_id == session_id
                and message.recipient == recipient
                and not message.read
            ):
                message.read = True
                found.append(deepcopy(message))
        return found

    async def add_event(self, event: SessionEvent) -> SessionEvent:
        self.events.append(deepcopy(event))
        return deepcopy(event)

    async def list_events(
        self, session_id: str, after: datetime | None = None, limit: int = 100
    ) -> list[SessionEvent]:
        found = [
            deepcopy(event)
            for event in self.events
            if event.session_id == session_id
            and (after is None or event.created_at > after)
        ]
        return sorted(found, key=lambda event: event.created_at)[:limit]
