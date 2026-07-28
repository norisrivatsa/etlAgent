from __future__ import annotations

import asyncio
from typing import Any, cast

from app.agents import base as agents_base
from app.agents.agents import build_agents
from app.agents.connector_specs import missing_fields
from app.config import Settings
from app.llm import LLMRouter
from app.models import (
    AgentTask,
    Artifact,
    ChatMessage,
    Decision,
    EventType,
    NextStep,
    PlannerResponse,
    RequirementState,
    SessionEvent,
    SessionState,
    SessionStatus,
    TopicDeclaration,
    WorkerResponse,
)
from app.repositories import StateRepository
from app.tools import ToolRegistry

# Executor deploys real infrastructure — only reachable from the dedicated /deploy
# action, never from a Planner-authored next_step.
PLANNER_DISPATCHABLE_AGENTS = {"connect", "ksqldb", "evaluator", "edge_case", "debug"}

# How many of the most recent chat turns the Planner always sees, regardless
# of starring. Starred messages are added on top of this, however old they are.
RECENT_MESSAGE_COUNT = 10

# Hard cap on Planner calls within a single handle_user_message turn. Dispatching
# "connect"/"ksqldb" naturally ends the loop (they produce artifacts awaiting
# approval), but "evaluator"/"edge_case"/"debug" don't — the loop only continues
# because the Planner itself decides to keep going. Observed in practice: asked to
# "re-run" a review, the Planner kept re-dispatching evaluator/edge_case turn after
# turn even after they'd already succeeded, looping indefinitely (and burning a real
# LLM call each time) with no natural stopping condition. This cap turns that into a
# reported error instead of an unbounded request.
MAX_TURN_ITERATIONS = 6


class Orchestrator:
    """Owns the Planner/Worker dispatch loop. Synchronous per request — no
    background queue — because the Planner only ever gets re-invoked after a
    phase is fully complete, and the approval relay needs no LLM judgment (see
    prompts/agent_class_implementation.md)."""

    def __init__(
        self,
        llm: LLMRouter,
        tools: ToolRegistry,
        repository: StateRepository,
        settings: Settings,
    ):
        self.llm = llm
        self.tools = tools
        self.repository = repository
        self.settings = settings

    async def handle_user_message(
        self, state: SessionState, message: str, focus_artifact_id: str | None = None
    ) -> tuple[SessionState, str]:
        agents = build_agents(state.config, self.llm, self.tools)
        if message:
            event_data: dict[str, Any] = {"message": message}
            metadata: dict[str, Any] = {"source": "user"}
            if focus_artifact_id:
                focused = next(
                    (a for a in state.whiteboard.artifacts if a.artifact_id == focus_artifact_id),
                    None,
                )
                if focused:
                    event_data["artifact_id"] = focused.artifact_id
                    event_data["artifact_name"] = focused.name
                    metadata["artifact_id"] = focused.artifact_id
                    metadata["artifact_name"] = focused.name
            # Persisted to the session document immediately, before the Planner
            # ever sees it — the session collection is the durable source of
            # truth for chat, not just the live event stream.
            await self._add_chat_message(state, "user", message, metadata)
            await self._emit(state, EventType.USER_MESSAGE, "user", event_data)

        last_reply = ""
        iterations = 0
        while True:
            iterations += 1
            if iterations > MAX_TURN_ITERATIONS:
                last_reply = (
                    f"Stopped after {MAX_TURN_ITERATIONS} automatic steps in this turn without "
                    "concluding — send another message to continue."
                )
                # Chat reply first, ERROR event last — deriveNodeStates() on the frontend
                # treats a planner agent_message as "back to success" and an ERROR event as
                # the definitive last word for this turn, so order matters here.
                await self._emit_chat(state, last_reply)
                await self._emit(
                    state, EventType.ERROR, "planner", {"error": "max_turn_iterations_exceeded"}
                )
                state.status = SessionStatus.REQUIREMENTS
                return state, last_reply

            # Persisted immediately (not just returned for the caller's single end-of-turn
            # save) so anyone polling GET /sessions/{id} sees "Planning" for the whole
            # duration of this LLM call, however long it takes — previously this was only
            # ever visible after the entire (possibly multi-iteration) turn had finished.
            state.status = SessionStatus.PLANNING
            await self.repository.save_session(state)
            try:
                planner_raw = await agents["planner"].run(
                    AgentTask(
                        session_id=state.session_id,
                        agent="planner",
                        instruction="Gather requirements and decide next steps",
                        context=await self._planner_context(state, message, focus_artifact_id),
                    )
                )
                plan = PlannerResponse.model_validate(planner_raw)
            except Exception as exc:
                # Unlike worker failures (caught per-task in run_phase and represented as
                # data), a broken Planner call has no partial result to fall back on — the
                # whole turn produced nothing. Surface it the same way a worker failure
                # would be surfaced (an ERROR event + a chat reply) instead of letting the
                # exception blow up the request with nothing persisted. Chat reply first,
                # ERROR event last — see the matching comment above for why order matters.
                last_reply = f"The Planner didn't respond: {exc}"
                await self._emit_chat(state, last_reply)
                await self._emit(state, EventType.ERROR, "planner", {"error": str(exc)})
                state.status = SessionStatus.REQUIREMENTS
                return state, last_reply

            # focus_artifact_id only scopes the Planner call that answers this specific
            # message — subsequent loop iterations (worker results feeding back in) are
            # general plan continuation again.
            focus_artifact_id = None
            self._apply_patch(state, plan.requirements_patch)
            if plan.pipeline_notes is not None:
                state.whiteboard.pipeline_notes = plan.pipeline_notes
            self._upsert_topics(state, plan.topics)
            await self._emit_chat(state, plan.reply_to_user)
            last_reply = plan.reply_to_user or last_reply

            if not plan.next_steps:
                state.status = (
                    SessionStatus.READY if plan.awaiting == "done" else SessionStatus.REQUIREMENTS
                )
                return state, last_reply

            # "Generating" specifically means creating pipeline artifacts (connector configs,
            # ksqlDB statements) — evaluator/edge_case/debug dispatches are reviews, not
            # generation, so they leave the status at the "planning" just persisted above.
            if any(step.agent in {"connect", "ksqldb"} for step in plan.next_steps):
                state.status = SessionStatus.GENERATING
                await self.repository.save_session(state)

            results = await self.run_phase(state, agents, plan.next_steps)

            if not results:
                # every next_step this turn targeted a non-dispatchable agent —
                # nothing ran, so there's nothing new to re-plan from either.
                state.status = SessionStatus.REQUIREMENTS
                return state, last_reply

            artifacts = self._collect_artifacts(state, results)

            if artifacts:
                state.whiteboard.artifacts.extend(artifacts)
                state.status = SessionStatus.AWAITING_APPROVAL
                state.pending_approval = results[0][0].phase
                last_reply = self._approval_prompt(results[0][0].phase, artifacts)
                await self._emit_chat(state, last_reply)
                return state, last_reply

            state.status = SessionStatus.PLANNING
            message = ""  # next Planner call has no new user text, just fresh worker results

    async def handle_approval(
        self, state: SessionState, approved: bool, comment: str | None
    ) -> tuple[SessionState, str]:
        agents = build_agents(state.config, self.llm, self.tools)
        await self._emit(state, EventType.APPROVAL, "user", {"approved": approved, "comment": comment})
        pending = [a for a in state.whiteboard.artifacts if a.status == "proposed"]

        if not approved:
            for artifact in pending:
                artifact.status = "rejected"
            state.pending_approval = None
            return await self.handle_user_message(
                state, comment or "Plan rejected, please revise."
            )

        planner = cast(agents_base.PlannerAgent, agents["planner"])
        for artifact in pending:
            await planner.commit_artifact(
                artifact, state.session_id, self.settings.deployment_root
            )
            if artifact.kind == "connector":
                state.whiteboard.connectors.append(artifact.content)
            else:
                state.whiteboard.ksqldb_objects.append(artifact.content)

        state.pending_approval = None
        return await self.handle_user_message(state, "")

    async def handle_artifact_approval(
        self, state: SessionState, artifact_id: str, approved: bool, comment: str | None
    ) -> tuple[SessionState, str]:
        """Approve/reject exactly one artifact rather than the whole phase. Caller
        (SessionService) has already verified the artifact exists and is "proposed"."""
        agents = build_agents(state.config, self.llm, self.tools)
        await self._emit(
            state,
            EventType.APPROVAL,
            "user",
            {"approved": approved, "comment": comment, "artifact_id": artifact_id},
        )

        artifact = next(a for a in state.whiteboard.artifacts if a.artifact_id == artifact_id)
        if approved:
            planner = cast(agents_base.PlannerAgent, agents["planner"])
            await planner.commit_artifact(artifact, state.session_id, self.settings.deployment_root)
            if artifact.kind == "connector":
                state.whiteboard.connectors.append(artifact.content)
            else:
                state.whiteboard.ksqldb_objects.append(artifact.content)
        else:
            artifact.status = "rejected"

        phase = artifact.phase
        still_pending = [
            a for a in state.whiteboard.artifacts if a.phase == phase and a.status == "proposed"
        ]
        if still_pending:
            return state, ""

        state.pending_approval = None
        rejected_names = [
            a.name for a in state.whiteboard.artifacts if a.phase == phase and a.status == "rejected"
        ]
        if rejected_names:
            default_comment = f"Rejected: {', '.join(rejected_names)}."
            return await self.handle_user_message(state, comment or default_comment)
        return await self.handle_user_message(state, "")

    async def run_phase(
        self, state: SessionState, agents: dict[str, Any], next_steps: list[NextStep]
    ) -> list[tuple[AgentTask, WorkerResponse]]:
        steps = []
        for step in next_steps:
            if step.agent in PLANNER_DISPATCHABLE_AGENTS:
                steps.append(step)
            else:
                state.whiteboard.decisions.append(
                    Decision(
                        action="dropped_next_step",
                        reason=f"'{step.agent}' is not planner-dispatchable",
                    )
                )

        tasks = [
            AgentTask(
                session_id=state.session_id,
                agent=step.agent,
                instruction=step.instruction,
                context=step.context_slice,
                phase=step.phase,
            )
            for step in steps
        ]
        for task in tasks:
            state.whiteboard.decisions.append(
                Decision(action="dispatch", reason=f"{task.agent}: {task.instruction}")
            )
            await self._emit(
                state,
                EventType.TASK,
                task.agent,
                {"task_id": task.task_id, "agent": task.agent, "status": "pending"},
            )

        raw_results = await asyncio.gather(
            *(agents[task.agent].run(task) for task in tasks), return_exceptions=True
        )

        results: list[tuple[AgentTask, WorkerResponse]] = []
        for task, raw in zip(tasks, raw_results):
            if isinstance(raw, Exception):
                await self._emit(
                    state,
                    EventType.ERROR,
                    task.agent,
                    {"task_id": task.task_id, "agent": task.agent, "error": str(raw)},
                )
                results.append((task, WorkerResponse(status="failed", summary=str(raw))))
            else:
                await self._emit(
                    state,
                    EventType.TASK,
                    task.agent,
                    {"task_id": task.task_id, "agent": task.agent, "status": "completed"},
                )
                results.append((task, WorkerResponse.model_validate(raw)))
        return results

    def _collect_artifacts(
        self, state: SessionState, results: list[tuple[AgentTask, WorkerResponse]]
    ) -> list[Artifact]:
        artifacts: list[Artifact] = []
        for task, response in results:
            revises_id = task.context.get("revises_artifact_id")
            if revises_id:
                for old in state.whiteboard.artifacts:
                    if old.artifact_id == revises_id and old.status == "proposed":
                        old.status = "superseded"

            if task.agent == "connect":
                for index, item in enumerate(response.artifacts):
                    name = item.get("name") or f"connector_{task.task_id[:8]}_{index}"
                    artifacts.append(
                        Artifact(
                            agent="connect",
                            kind="connector",
                            name=name,
                            content=item,
                            phase=task.phase,
                        )
                    )
            elif task.agent == "ksqldb":
                for index, item in enumerate(response.artifacts):
                    layer = item.get("layer", "statement")
                    name = item.get("object_name") or f"{layer}_{index}_{task.task_id[:8]}"
                    artifacts.append(
                        Artifact(
                            agent="ksqldb",
                            kind="ksql_statement",
                            name=name,
                            content=item,
                            phase=task.phase,
                        )
                    )
            elif task.agent == "evaluator":
                state.whiteboard.evaluation.findings.extend(
                    {"detail": warning} for warning in response.warnings
                )
                state.whiteboard.evaluation.approved = (
                    response.status == "ok" and not response.warnings
                )
            elif task.agent == "edge_case":
                state.whiteboard.evaluation.edge_cases.extend(
                    {"detail": warning} for warning in response.warnings
                )
            # debug: nothing structured to fold in beyond the chat reply already
            # emitted from plan.reply_to_user next turn.
        return artifacts

    async def _planner_context(
        self, state: SessionState, message: str, focus_artifact_id: str | None = None
    ) -> dict[str, Any]:
        requirements = state.whiteboard.requirements.model_dump(mode="json")
        for table in requirements.get("source", {}).get("tables", []):
            table["missing_fields"] = missing_fields(
                table.get("connector_type", ""), table.get("mode"), table
            )
        focused = next(
            (a for a in state.whiteboard.artifacts if a.artifact_id == focus_artifact_id),
            None,
        )
        return {
            "pipeline_name": state.pipeline_name,
            "requirements": requirements,
            "plan": state.whiteboard.plan.model_dump(mode="json"),
            "artifacts": [a.model_dump(mode="json") for a in state.whiteboard.artifacts],
            "evaluation": state.whiteboard.evaluation.model_dump(mode="json"),
            "pipeline_notes": state.whiteboard.pipeline_notes,
            "environment": {
                "kafka_bootstrap_servers": state.config.kafka_bootstrap_servers,
                "connect_url": state.config.connect_url,
                "ksqldb_url": state.config.ksqldb_url,
            },
            "user_message": message,
            "conversation_history": self._conversation_history(state),
            "focused_artifact": focused.model_dump(mode="json") if focused else None,
        }

    @staticmethod
    def _conversation_history(state: SessionState) -> list[dict[str, Any]]:
        """The last RECENT_MESSAGE_COUNT chat turns, plus every starred turn no
        matter how old — starring is how the user keeps something in the
        Planner's context permanently (see prompts/agent_class_implementation.md).
        Anything older than this window is reachable only through the Planner's
        query_messages tool — state.messages already holds the full session
        history in memory, so no repository round-trip is needed here."""
        turns = [
            {
                "role": message.role,
                "content": message.content,
                "starred": message.starred,
                "created_at": message.created_at.isoformat(),
            }
            for message in sorted(state.messages, key=lambda message: message.created_at)
        ]
        recent = turns[-RECENT_MESSAGE_COUNT:]
        recent_keys = {turn["created_at"] for turn in recent}
        starred = [turn for turn in turns if turn["starred"] and turn["created_at"] not in recent_keys]
        merged = recent + starred
        merged.sort(key=lambda turn: turn["created_at"])
        return merged

    @staticmethod
    def _apply_patch(state: SessionState, patch: dict[str, Any]) -> None:
        field_names = set(RequirementState.model_fields)
        aliases = {
            field.validation_alias: name
            for name, field in RequirementState.model_fields.items()
            if isinstance(field.validation_alias, str)
        }
        known = {
            aliases.get(key, key): value
            for key, value in patch.items()
            if key in field_names or key in aliases
        }
        state.whiteboard.requirements = state.whiteboard.requirements.model_copy(update=known)

    @staticmethod
    def _upsert_topics(state: SessionState, topics: list[TopicDeclaration]) -> None:
        """Merge the Planner's topic declarations into whiteboard.topics by name —
        an addition, not a wholesale replacement, since topics accumulate across
        phases (source-phase raw topics, then the final ksqlDB output topic)."""
        if not topics:
            return
        by_name = {topic["name"]: topic for topic in state.whiteboard.topics}
        for declaration in topics:
            by_name[declaration.name] = declaration.model_dump(mode="json")
        state.whiteboard.topics = list(by_name.values())

    @staticmethod
    def _approval_prompt(phase: str | None, artifacts: list[Artifact]) -> str:
        names = ", ".join(artifact.name for artifact in artifacts)
        return f"Generated {len(artifacts)} {phase} artifact(s): {names}. Approve to continue?"

    async def _emit_chat(self, state: SessionState, text: str) -> None:
        if not text:
            return
        state.whiteboard.decisions.append(Decision(action="agent_message", reason=text))
        await self._add_chat_message(state, "assistant", text, {"source": "planner"})
        await self._emit(state, EventType.AGENT_MESSAGE, "planner", {"reply": text})

    async def _add_chat_message(
        self, state: SessionState, role: str, content: str, metadata: dict[str, Any]
    ) -> None:
        """Human<->planner chat only — never agent-to-agent traffic. Written to
        the session document immediately, and appended in-memory so the rest of
        this turn (and _conversation_history) sees it right away."""
        message = ChatMessage(
            session_id=state.session_id, role=role, content=content, metadata=metadata
        )
        await self.repository.add_chat_message(state.session_id, message)
        state.messages.append(message)

    async def _emit(
        self, state: SessionState, event_type: EventType, source: str, data: dict[str, Any]
    ) -> None:
        await self.repository.add_event(
            SessionEvent(session_id=state.session_id, type=event_type, source=source, data=data)
        )
