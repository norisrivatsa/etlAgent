from __future__ import annotations

from datetime import datetime

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
    CreateSessionRequest,
    DeployMode,
    DeployRequest,
    DeploymentStatus,
    EventList,
    EventType,
    ModelProvider,
    SessionConfig,
    SessionEvent,
    SessionList,
    SessionMessageResponse,
    SessionState,
    SessionStatus,
    UserMessageRequest,
)
from app.orchestrator import Orchestrator
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
        """Retrieve chat messages (USER_MESSAGE and AGENT_MESSAGE events) for a session."""
        await self.get_session(session_id)
        events = await self.repository.list_events(session_id, None, limit)
        chat_messages = [
            message
            for message in (self._event_to_chat_message(event) for event in events)
            if message is not None
        ]
        return ChatMessageList(messages=chat_messages)

    async def star_message(
        self, session_id: str, message_id: str, starred: bool
    ) -> ChatMessage:
        await self.get_session(session_id)
        event = await self.repository.set_event_starred(session_id, message_id, starred)
        message = self._event_to_chat_message(event) if event else None
        if message is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Message not found")
        return message

    @staticmethod
    def _event_to_chat_message(event: SessionEvent) -> ChatMessage | None:
        if event.type == EventType.USER_MESSAGE:
            metadata = {"source": event.source}
            if event.data.get("artifact_id"):
                metadata["artifact_id"] = event.data["artifact_id"]
                metadata["artifact_name"] = event.data.get("artifact_name", "")
            return ChatMessage(
                message_id=event.event_id,
                session_id=event.session_id,
                role="user",
                content=event.data.get("message", ""),
                starred=event.starred,
                metadata=metadata,
                created_at=event.created_at,
            )
        if event.type == EventType.AGENT_MESSAGE and event.source == "planner":
            return ChatMessage(
                message_id=event.event_id,
                session_id=event.session_id,
                role="assistant",
                content=event.data.get("reply", ""),
                starred=event.starred,
                metadata={"source": event.source},
                created_at=event.created_at,
            )
        return None

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
