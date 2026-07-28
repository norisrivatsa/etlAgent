from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from app.agents.agents import build_agents
from app.config import Settings
from app.deployment import DeploymentPackageBuilder
from app.llm import LLMRouter
from app.models import (
    AgentModelConfig,
    AgentTask,
    ApprovalRequest,
    ChatMessage,
    ChatMessageList,
    ConnectorStatus,
    CreateSessionRequest,
    DeployMode,
    DeployRequest,
    DeploymentStatus,
    EventList,
    EventType,
    ModelProvider,
    PipelineGraph,
    SessionConfig,
    SessionEvent,
    SessionList,
    SessionMessageResponse,
    SessionState,
    SessionStatus,
    UserMessageRequest,
)
from app.orchestrator import Orchestrator
from app.pipeline_graph import build_pipeline_graph
from app.repositories import StateRepository
from app.tools import ToolRegistry


class SessionService:
    def __init__(
        self,
        repository: StateRepository,
        orchestrator: Orchestrator,
        llm: LLMRouter,
        tools: ToolRegistry,
        settings: Settings,
    ):
        self.repository = repository
        self.orchestrator = orchestrator
        self.llm = llm
        self.tools = tools
        self.settings = settings
        self.packages = DeploymentPackageBuilder(settings.deployment_root)

    async def create_session(self, request: CreateSessionRequest) -> SessionState:
        config = (
            request.config
            if "config" in request.model_fields_set
            else self._default_session_config()
        )
        state = SessionState(pipeline_name=request.pipeline_name, config=config)
        if request.initial_requirements:
            Orchestrator._apply_patch(state, request.initial_requirements)
        await self.repository.create_session(state)
        await self.repository.add_event(
            SessionEvent(
                session_id=state.session_id,
                type=EventType.SESSION,
                source="planner",
                data={"status": "created", "pipeline_name": state.pipeline_name},
            )
        )
        return state

    async def list_sessions(self, limit: int) -> SessionList:
        sessions = await self.repository.list_sessions(limit)
        return SessionList(sessions=sessions)

    async def get_session(self, session_id: str) -> SessionState:
        state = await self.repository.get_session(session_id)
        if not state:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Session not found")
        return state

    async def message(
        self, session_id: str, request: UserMessageRequest
    ) -> SessionMessageResponse:
        state = await self.get_session(session_id)
        state, reply = await self.orchestrator.handle_user_message(
            state, request.message, request.artifact_id
        )
        await self.repository.save_session(state)
        return SessionMessageResponse(session=state, reply=reply)

    async def approve(
        self, session_id: str, request: ApprovalRequest
    ) -> SessionMessageResponse:
        state = await self.get_session(session_id)
        if not state.pending_approval:
            raise HTTPException(status.HTTP_409_CONFLICT, "No approval is pending")
        state, reply = await self.orchestrator.handle_approval(
            state, request.approved, request.comment
        )
        await self.repository.save_session(state)
        return SessionMessageResponse(session=state, reply=reply)

    async def approve_artifact(
        self, session_id: str, artifact_id: str, request: ApprovalRequest
    ) -> SessionMessageResponse:
        state = await self.get_session(session_id)
        artifact = next(
            (a for a in state.whiteboard.artifacts if a.artifact_id == artifact_id), None
        )
        if artifact is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Artifact not found")
        if artifact.status != "proposed":
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Artifact is not pending approval (status={artifact.status})",
            )
        state, reply = await self.orchestrator.handle_artifact_approval(
            state, artifact_id, request.approved, request.comment
        )
        await self.repository.save_session(state)
        return SessionMessageResponse(session=state, reply=reply)

    async def deploy(self, session_id: str, request: DeployRequest) -> SessionState:
        state = await self.get_session(session_id)
        if state.status not in {SessionStatus.READY, SessionStatus.DEPLOYED}:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Session is not deployable from status {state.status}",
            )
        package = await self.packages.build(state)
        state.whiteboard.deployment_status = DeploymentStatus(
            state="package_generated", package_path=str(package)
        )
        if request.mode == DeployMode.PACKAGE:
            await self.repository.save_session(state)
            await self.repository.add_event(
                SessionEvent(
                    session_id=state.session_id,
                    type=EventType.DEPLOYMENT,
                    source="executor",
                    data={"mode": "package", "path": str(package)},
                )
            )
            return state

        state.status = SessionStatus.DEPLOYING
        await self.repository.save_session(state)
        agents = build_agents(state.config, self.llm, self.tools)
        task = AgentTask(
            session_id=state.session_id,
            agent="executor",
            instruction="Deploy connector and ksqlDB artifacts",
            context={
                "connect_url": state.config.connect_url or self.settings.connect_url,
                "ksqldb_url": state.config.ksqldb_url or self.settings.ksqldb_url,
                "connector_configs": state.whiteboard.connectors,
                "ksql_statements": [
                    item["statement"]
                    for item in state.whiteboard.ksqldb_objects
                    if item.get("statement")
                ],
            },
        )
        result = await agents["executor"].run(task)
        succeeded = result.get("status") == "ok"
        state.whiteboard.deployment_status = DeploymentStatus(
            state="deployed" if succeeded else "failed",
            package_path=str(package),
            records=result.get("records", []),
            error=None if succeeded else result.get("summary"),
        )
        state.status = SessionStatus.DEPLOYED if succeeded else SessionStatus.FAILED
        await self.repository.save_session(state)
        return state

    async def events(
        self,
        session_id: str,
        after: datetime | None,
        limit: int,
    ) -> EventList:
        await self.get_session(session_id)
        events = await self.repository.list_events(session_id, after, limit)
        return EventList(
            events=events,
            next_cursor=events[-1].created_at if events else after,
        )

    async def chat_messages(self, session_id: str, limit: int) -> ChatMessageList:
        """Retrieve human<->planner chat messages for a session, most recent
        `limit` — stored directly on the session document, see SessionState.messages."""
        state = await self.get_session(session_id)
        if not state.messages:
            await self._backfill_chat_messages(state)
        messages = await self.repository.list_chat_messages(session_id, limit)
        return ChatMessageList(messages=messages)

    async def _backfill_chat_messages(self, state: SessionState) -> None:
        """One-time migration for sessions created before chat moved onto the
        session document (SessionState.messages) — reconstructs them from the
        events log so pre-existing chat history doesn't disappear from the UI.
        No-op (and cheap) for a session that never had any chat, and self-heals
        exactly once per session since messages are non-empty after this runs."""
        events = await self.repository.list_events(state.session_id, None, 10_000)
        backfilled: list[ChatMessage] = []
        for event in events:
            if event.type == EventType.USER_MESSAGE:
                metadata = {"source": event.source}
                if event.data.get("artifact_id"):
                    metadata["artifact_id"] = event.data["artifact_id"]
                    metadata["artifact_name"] = event.data.get("artifact_name", "")
                backfilled.append(
                    ChatMessage(
                        session_id=state.session_id,
                        role="user",
                        content=event.data.get("message", ""),
                        starred=event.starred,
                        metadata=metadata,
                        created_at=event.created_at,
                    )
                )
            elif event.type == EventType.AGENT_MESSAGE and event.source == "planner":
                backfilled.append(
                    ChatMessage(
                        session_id=state.session_id,
                        role="assistant",
                        content=event.data.get("reply", ""),
                        starred=event.starred,
                        metadata={"source": event.source},
                        created_at=event.created_at,
                    )
                )
        for message in backfilled:
            await self.repository.add_chat_message(state.session_id, message)
        state.messages = backfilled

    async def star_message(
        self, session_id: str, message_id: str, starred: bool
    ) -> ChatMessage:
        await self.get_session(session_id)
        message = await self.repository.set_chat_message_starred(session_id, message_id, starred)
        if message is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
        return message

    async def pipeline_graph(self, session_id: str) -> PipelineGraph:
        """Nodes/edges for the Pipeline Graph view, with live Kafka Connect
        status merged onto connector nodes — polled by the frontend every 30s."""
        state = await self.get_session(session_id)
        nodes, edges = build_pipeline_graph(state)
        statuses = await self.connector_statuses(state)
        for node in nodes:
            if node.type in ("source_connector", "sink_connector"):
                node.connector_status = statuses.get(node.name)
        return PipelineGraph(nodes=nodes, edges=edges)

    async def connector_statuses(self, state: SessionState) -> dict[str, ConnectorStatus]:
        """Live status per committed connector, reduced to the color the graph
        needs: red (FAILED), green (RUNNING, all tasks healthy), orange
        (RUNNING, some tasks failed), grey (not deployed yet, or the live
        lookup itself failed -- e.g. Connect unreachable)."""
        connector_names = [
            artifact.name
            for artifact in state.whiteboard.artifacts
            if artifact.kind == "connector" and artifact.status == "committed"
        ]
        if not connector_names:
            return {}
        if state.whiteboard.deployment_status.state != "deployed":
            return {
                name: ConnectorStatus(color="grey", detail="not deployed yet")
                for name in connector_names
            }

        connect_url = state.config.connect_url or self.settings.connect_url
        raw_results = await asyncio.gather(
            *(
                self.tools.execute("connector_status", connect_url=connect_url, connector_name=name)
                for name in connector_names
            ),
            return_exceptions=True,
        )
        statuses: dict[str, ConnectorStatus] = {}
        for name, raw in zip(connector_names, raw_results):
            if isinstance(raw, Exception):
                statuses[name] = ConnectorStatus(color="grey", detail=str(raw))
            else:
                statuses[name] = self._reduce_connector_status(raw)
        return statuses

    @staticmethod
    def _reduce_connector_status(raw: dict[str, Any]) -> ConnectorStatus:
        connector_state = (raw.get("connector") or {}).get("state", "UNKNOWN")
        tasks = raw.get("tasks") or []
        failed_tasks = sum(1 for task in tasks if task.get("state") == "FAILED")
        total_tasks = len(tasks)
        if connector_state == "FAILED":
            color = "red"
        elif connector_state == "RUNNING":
            color = "orange" if failed_tasks else "green"
        else:
            color = "grey"
        return ConnectorStatus(
            color=color, state=connector_state, failed_tasks=failed_tasks, total_tasks=total_tasks
        )

    def _default_session_config(self) -> SessionConfig:
        if self.settings.openai_api_key:
            model_config = AgentModelConfig(
                provider=ModelProvider.OPENAI,
                model=self.settings.openai_model,
            )
        else:
            model_config = AgentModelConfig(
                provider=ModelProvider.OLLAMA,
                model=self.settings.ollama_model,
            )
        return SessionConfig(
            planner=model_config,
            connect=model_config,
            ksqldb=model_config,
            evaluator=model_config,
            edge_case=model_config,
            executor=model_config,
            debug=model_config,
        )
