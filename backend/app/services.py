from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status

from app.config import Settings
from app.deployment import DeploymentPackageBuilder
from app.models import (
    AgentModelConfig,
    ApprovalRequest,
    ChatMessage,
    ChatMessageList,
    CreateSessionRequest,
    Decision,
    DeployMode,
    DeployRequest,
    DeploymentStatus,
    EventList,
    EventType,
    ModelProvider,
    PlannerLLMOutput,
    PlannerResponse,
    RequirementState,
    SessionConfig,
    SessionList,
    SessionState,
    SessionStatus,
    UserMessageRequest,
    VerificationRequest,
    VerificationStatus,
    utc_now,
)
from app.repositories import StateRepository
from app.runtime import RuntimeManager


class SessionService:
    def __init__(
        self,
        repository: StateRepository,
        runtimes: RuntimeManager,
        settings: Settings,
    ):
        self.repository = repository
        self.runtimes = runtimes
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
            state.whiteboard.requirements = state.whiteboard.requirements.model_copy(
                update=self._known_requirement_patch(request.initial_requirements)
            )
        await self.repository.create_session(state)
        runtime = await self.runtimes.get(state)
        await runtime.emit(
            EventType.SESSION,
            "planner",
            {"status": "created", "pipeline_name": state.pipeline_name},
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
    ) -> PlannerResponse:
        state = await self.get_session(session_id)
        runtime = await self.runtimes.get(state)
        await runtime.emit(EventType.USER_MESSAGE, "user", {"message": request.message})
        task = await runtime.submit(
            "planner",
            "Gather requirements and update the pipeline plan",
            {
                "pipeline_name": state.pipeline_name,
                "whiteboard": state.whiteboard.model_dump(mode="json"),
                "user_message": request.message,
            },
        )
        if not task.result:
            raise HTTPException(
                status.HTTP_502_BAD_GATEWAY,
                task.error or "Planner agent failed",
            )
        output = PlannerLLMOutput.model_validate(task.result)
        patch = self._known_requirement_patch(output.requirements_patch)
        state.whiteboard.requirements = state.whiteboard.requirements.model_copy(
            update=patch
        )
        state.whiteboard.requirements.open_questions = output.open_questions
        if output.plan:
            state.whiteboard.plan = output.plan
            state.whiteboard.topics = output.plan.topics
        if output.ready_for_approval:
            state.status = SessionStatus.AWAITING_APPROVAL
            state.pending_approval = "pipeline_plan"
        else:
            state.status = SessionStatus.REQUIREMENTS
        state.whiteboard.revision += 1
        state.whiteboard.updated_at = utc_now()
        state.whiteboard.decisions.append(
            Decision(
                action=(
                    "request_approval"
                    if output.ready_for_approval
                    else "gather_requirements"
                ),
                reason=output.reply,
            )
        )
        await self.repository.save_session(state)
        await runtime.emit(
            EventType.AGENT_MESSAGE,
            "planner",
            {"reply": output.reply, "open_questions": output.open_questions},
        )
        return PlannerResponse(session=state, reply=output.reply, tasks=[task])

    async def approve(
        self, session_id: str, request: ApprovalRequest
    ) -> PlannerResponse:
        state = await self.get_session(session_id)
        if not state.pending_approval:
            raise HTTPException(status.HTTP_409_CONFLICT, "No approval is pending")
        runtime = await self.runtimes.get(state)
        await runtime.emit(
            EventType.APPROVAL,
            "user",
            {"approved": request.approved, "comment": request.comment},
        )
        if not request.approved:
            state.status = SessionStatus.REQUIREMENTS
            state.pending_approval = None
            state.whiteboard.decisions.append(
                Decision(
                    action="plan_rejected", reason=request.comment or "Rejected by user"
                )
            )
            await self.repository.save_session(state)
            return PlannerResponse(
                session=state,
                reply="Plan rejected. Provide the required changes in a new message.",
            )

        state.status = SessionStatus.GENERATING
        state.pending_approval = None
        await self.repository.save_session(state)
        plan_context = {
            "requirements": state.whiteboard.requirements.model_dump(mode="json"),
            "plan": state.whiteboard.plan.model_dump(mode="json"),
        }
        connect_task, ksql_task, edge_task = await asyncio.gather(
            runtime.submit(
                "connect", "Generate connector configurations", plan_context
            ),
            runtime.submit("ksqldb", "Generate ksqlDB statements", plan_context),
            runtime.submit("edge_case", "Review pipeline failure modes", plan_context),
        )
        tasks = [connect_task, ksql_task, edge_task]
        failed = [task for task in tasks if not task.result]
        if failed:
            state.status = SessionStatus.FAILED
            await self.repository.save_session(state)
            return PlannerResponse(
                session=state,
                reply="Artifact generation failed.",
                tasks=tasks,
            )

        connect_result = connect_task.result or {}
        ksql_result = ksql_task.result or {}
        state.whiteboard.connectors = connect_result.get("connector_configs", [])
        state.whiteboard.ksqldb_objects = self._ksql_objects(ksql_result)
        state.whiteboard.evaluation.edge_cases = (edge_task.result or {}).get(
            "edge_cases", []
        )
        evaluator_task = await runtime.submit(
            "evaluator",
            "Review generated pipeline artifacts",
            {
                **plan_context,
                "connect": connect_result,
                "ksqldb": ksql_result,
                "edge_cases": state.whiteboard.evaluation.edge_cases,
            },
        )
        tasks.append(evaluator_task)
        evaluation = evaluator_task.result or {}
        state.whiteboard.evaluation.findings = evaluation.get("findings", [])
        state.whiteboard.evaluation.approved = bool(evaluation.get("approved", False))
        state.status = (
            SessionStatus.READY
            if state.whiteboard.evaluation.approved
            else SessionStatus.AWAITING_APPROVAL
        )
        state.pending_approval = (
            None if state.status == SessionStatus.READY else "evaluation_findings"
        )
        state.whiteboard.revision += 1
        state.whiteboard.updated_at = utc_now()
        await self.repository.save_session(state)
        reply = (
            "Artifacts generated and evaluation passed."
            if state.status == SessionStatus.READY
            else "Artifacts generated, but evaluation findings require approval or revision."
        )
        return PlannerResponse(session=state, reply=reply, tasks=tasks)

    async def deploy(self, session_id: str, request: DeployRequest) -> SessionState:
        state = await self.get_session(session_id)
        if state.status not in {
            SessionStatus.READY,
            SessionStatus.DEPLOYED,
            SessionStatus.HEALTHY,
        }:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Session is not deployable from status {state.status}",
            )
        runtime = await self.runtimes.get(state)
        package = await self.packages.build(state)
        state.whiteboard.deployment_status = DeploymentStatus(
            state="package_generated", package_path=str(package)
        )
        if request.mode == DeployMode.PACKAGE:
            await self.repository.save_session(state)
            await runtime.emit(
                EventType.DEPLOYMENT,
                "executor",
                {"mode": "package", "path": str(package)},
            )
            return state

        state.status = SessionStatus.DEPLOYING
        await self.repository.save_session(state)
        task = await runtime.submit(
            "executor",
            "Deploy connector and ksqlDB artifacts",
            {
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
        result = task.result or {"success": False, "records": []}
        state.whiteboard.deployment_status = DeploymentStatus(
            state="deployed" if result.get("success") else "failed",
            package_path=str(package),
            records=result.get("records", []),
            error=task.error,
        )
        state.status = (
            SessionStatus.DEPLOYED if result.get("success") else SessionStatus.FAILED
        )
        await self.repository.save_session(state)
        return state

    async def verify(
        self, session_id: str, request: VerificationRequest
    ) -> SessionState:
        state = await self.get_session(session_id)
        if state.status not in {SessionStatus.DEPLOYED, SessionStatus.HEALTHY}:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Verification requires a deployed session",
            )
        runtime = await self.runtimes.get(state)
        state.status = SessionStatus.VERIFYING
        await self.repository.save_session(state)
        task = await runtime.submit(
            "verification",
            "Verify deployed pipeline health and correctness",
            {
                "connect_url": state.config.connect_url or self.settings.connect_url,
                "ksqldb_url": state.config.ksqldb_url or self.settings.ksqldb_url,
                "bootstrap_servers": state.config.kafka_bootstrap_servers
                or self.settings.kafka_bootstrap_servers,
                "connectors": state.whiteboard.connectors,
                "topics": state.whiteboard.topics,
                **request.model_dump(mode="json"),
            },
        )
        result = task.result or {"success": False, "checks": []}
        state.whiteboard.verification_status = VerificationStatus(
            state="passed" if result.get("success") else "failed",
            checks=result.get("checks", []),
            summary=task.error,
        )
        state.status = (
            SessionStatus.HEALTHY if result.get("success") else SessionStatus.FAILED
        )
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

        # Filter and transform to chat messages
        chat_messages = []
        for event in events:
            if event.type == EventType.USER_MESSAGE:
                chat_messages.append(
                    ChatMessage(
                        message_id=event.event_id,
                        session_id=event.session_id,
                        role="user",
                        content=event.data.get("message", ""),
                        metadata={"source": event.source},
                        created_at=event.created_at,
                    )
                )
            elif event.type == EventType.AGENT_MESSAGE and event.source == "planner":
                chat_messages.append(
                    ChatMessage(
                        message_id=event.event_id,
                        session_id=event.session_id,
                        role="assistant",
                        content=event.data.get("reply", ""),
                        metadata={
                            "source": event.source,
                            "open_questions": event.data.get("open_questions", []),
                        },
                        created_at=event.created_at,
                    )
                )

        return ChatMessageList(messages=chat_messages)

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
            verification=model_config,
        )

    @staticmethod
    def _known_requirement_patch(value: dict[str, Any]) -> dict[str, Any]:
        field_names = set(RequirementState.model_fields)
        aliases = {
            field.validation_alias: name
            for name, field in RequirementState.model_fields.items()
            if isinstance(field.validation_alias, str)
        }
        return {
            aliases.get(key, key): item
            for key, item in value.items()
            if key in field_names or key in aliases
        }

    @staticmethod
    def _ksql_objects(result: dict[str, Any]) -> list[dict[str, Any]]:
        objects = list(result.get("objects", []))
        known = {item.get("statement") for item in objects}
        for statement in result.get("statements", []):
            if statement not in known:
                objects.append({"type": "statement", "statement": statement})
        return objects
