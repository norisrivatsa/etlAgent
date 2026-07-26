from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest

from app.config import Settings
from app.llm import StubLLMRouter
from app.models import EventType, SessionEvent, SessionState, utc_now
from app.orchestrator import Orchestrator
from app.repositories import InMemoryStateRepository
from app.tools import ToolRegistry


class _RaisingLLMRouter:
    """Simulates an Ollama timeout/connect failure — generate_json never returns a value."""

    async def generate_json(self, config, system_prompt, user_prompt):
        raise RuntimeError("Ollama request timed out at http://localhost:11434 after 600.0 seconds")


class _StatusSpyRepository(InMemoryStateRepository):
    """Records every status passed to save_session, in order — used to confirm intermediate
    "planning"/"generating" states are actually persisted mid-turn, not just the final one."""

    def __init__(self) -> None:
        super().__init__()
        self.saved_statuses: list[str] = []

    async def save_session(self, state):
        self.saved_statuses.append(state.status.value)
        return await super().save_session(state)


def _base_responses() -> list[dict]:
    return [
        {
            "reply_to_user": "Got it — generating the orders connector.",
            "requirements_patch": {"source": {"type": "postgres", "table": "orders"}},
            "next_steps": [
                {
                    "agent": "connect",
                    "instruction": "Generate the orders connector",
                    "context_slice": {"table": "orders"},
                    "phase": "connect",
                }
            ],
            "awaiting": "agent:connect",
        },
        {
            "status": "ok",
            "artifacts": [
                {"name": "orders-source", "config": {"connector.class": "JdbcSourceConnector"}}
            ],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated orders-source connector",
        },
    ]


def _full_flow_responses() -> list[dict]:
    return _base_responses() + [
        {
            "reply_to_user": "Connector approved. Building the ksqlDB pipeline.",
            "requirements_patch": {},
            "next_steps": [
                {
                    "agent": "ksqldb",
                    "instruction": "Design the ksqlDB pipeline",
                    "context_slice": {"topics": ["orders.orders"]},
                    "phase": "ksqldb",
                }
            ],
            "awaiting": "agent:ksqldb",
        },
        {
            "status": "ok",
            "artifacts": [
                {"statement": "CREATE STREAM orders_raw ...;", "layer": "raw"},
                {"statement": "CREATE TABLE orders_agg ...;", "layer": "aggregate"},
            ],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated raw + aggregate pipeline",
        },
        {
            "reply_to_user": "Pipeline complete and ready to deploy.",
            "requirements_patch": {},
            "next_steps": [],
            "awaiting": "done",
        },
    ]


def _orchestrator(tmp_path: Path, responses: list[dict]) -> tuple[Orchestrator, InMemoryStateRepository]:
    repository = InMemoryStateRepository()
    settings = Settings(deployment_root=tmp_path)
    return Orchestrator(StubLLMRouter(responses), ToolRegistry(), repository, settings), repository


@pytest.mark.asyncio
async def test_full_multi_phase_flow_reaches_ready(tmp_path: Path) -> None:
    orchestrator, repository = _orchestrator(tmp_path, _full_flow_responses())
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Move postgres orders into mongo")
    assert state.status == "awaiting_approval"
    assert state.pending_approval == "connect"
    assert len(state.whiteboard.artifacts) == 1
    assert state.whiteboard.artifacts[0].status == "proposed"

    state, _ = await orchestrator.handle_approval(state, True, None)
    assert state.status == "awaiting_approval"
    assert state.pending_approval == "ksqldb"
    committed = [a for a in state.whiteboard.artifacts if a.status == "committed"]
    assert len(committed) == 1
    assert state.whiteboard.connectors[0]["name"] == "orders-source"

    state, reply = await orchestrator.handle_approval(state, True, None)
    assert state.status == "ready"
    assert len(state.whiteboard.ksqldb_objects) == 2
    assert "ready to deploy" in reply.lower()

    committed_files = list((tmp_path / state.session_id / "artifacts").glob("*.json"))
    assert len(committed_files) == 3  # 1 connector + 2 ksql statements


@pytest.mark.asyncio
async def test_planning_and_generating_status_persisted_mid_turn(tmp_path: Path) -> None:
    repository = _StatusSpyRepository()
    settings = Settings(deployment_root=tmp_path)
    orchestrator = Orchestrator(StubLLMRouter(_base_responses()), ToolRegistry(), repository, settings)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Move postgres orders into mongo")

    # "planning" (before the Planner call) then "generating" (before dispatching connect, which
    # produces pipeline artifacts) must both have been persisted mid-turn — calling the
    # orchestrator directly here (bypassing SessionService, which would add one more save of
    # the final state) isolates exactly what the orchestrator itself persists.
    assert repository.saved_statuses == ["planning", "generating"]
    assert state.status == "awaiting_approval"


@pytest.mark.asyncio
async def test_rejected_approval_resets_to_requirements_gathering(tmp_path: Path) -> None:
    responses = _base_responses() + [
        {
            "reply_to_user": "Understood, let's adjust the connector.",
            "requirements_patch": {},
            "next_steps": [],
            "awaiting": "user",
        }
    ]
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Move postgres orders into mongo")
    state, _ = await orchestrator.handle_approval(state, False, "Wrong table name")

    assert state.status == "requirements"
    assert state.pending_approval is None
    rejected = [a for a in state.whiteboard.artifacts if a.status == "rejected"]
    assert len(rejected) == 1


@pytest.mark.asyncio
async def test_executor_next_step_is_dropped_not_dispatched(tmp_path: Path) -> None:
    responses = [
        {
            "reply_to_user": "Deploying now.",
            "requirements_patch": {},
            "next_steps": [
                {
                    "agent": "executor",
                    "instruction": "deploy everything",
                    "context_slice": {},
                    "phase": "deploy",
                }
            ],
            "awaiting": "agent:executor",
        }
    ]
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "deploy it")

    # executor next_step was dropped, so no artifacts, no dispatch, plan just ends
    assert state.whiteboard.artifacts == []
    assert any(
        decision.action == "dropped_next_step" for decision in state.whiteboard.decisions
    )


def _two_connector_responses() -> list[dict]:
    return [
        {
            "reply_to_user": "Generating both connectors.",
            "requirements_patch": {},
            "next_steps": [
                {
                    "agent": "connect",
                    "instruction": "Generate the orders connector",
                    "context_slice": {"table": "orders"},
                    "phase": "connect",
                },
                {
                    "agent": "connect",
                    "instruction": "Generate the customers connector",
                    "context_slice": {"table": "customers"},
                    "phase": "connect",
                },
            ],
            "awaiting": "agent:connect",
        },
        {
            "status": "ok",
            "artifacts": [{"name": "orders-source", "config": {}}],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated orders-source connector",
        },
        {
            "status": "ok",
            "artifacts": [{"name": "customers-source", "config": {}}],
            "needs_approval": True,
            "warnings": [],
            "summary": "Generated customers-source connector",
        },
    ]


@pytest.mark.asyncio
async def test_artifact_approval_keeps_phase_pending_until_all_resolved(tmp_path: Path) -> None:
    responses = _two_connector_responses() + [
        {
            "reply_to_user": "Both connectors approved.",
            "requirements_patch": {},
            "next_steps": [],
            "awaiting": "done",
        }
    ]
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Two tables please")
    assert state.pending_approval == "connect"
    assert len(state.whiteboard.artifacts) == 2
    first, second = state.whiteboard.artifacts

    state, reply = await orchestrator.handle_artifact_approval(state, first.artifact_id, True, None)
    assert reply == ""
    assert state.pending_approval == "connect"  # second artifact still open
    assert first.status == "committed"
    assert second.status == "proposed"

    state, reply = await orchestrator.handle_artifact_approval(state, second.artifact_id, True, None)
    assert state.pending_approval is None
    assert state.status == "ready"
    assert second.status == "committed"
    assert "approved" in reply.lower()
    assert len(state.whiteboard.connectors) == 2


@pytest.mark.asyncio
async def test_artifact_rejection_reports_name_and_resumes_planning(tmp_path: Path) -> None:
    responses = _two_connector_responses() + [
        {
            "reply_to_user": "Let's fix the customers connector.",
            "requirements_patch": {},
            "next_steps": [],
            "awaiting": "user",
        }
    ]
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Two tables please")
    first, second = state.whiteboard.artifacts

    state, _ = await orchestrator.handle_artifact_approval(state, first.artifact_id, True, None)
    state, _ = await orchestrator.handle_artifact_approval(state, second.artifact_id, False, None)

    assert state.pending_approval is None
    assert second.status == "rejected"

    events = await repository.list_events(state.session_id, None, 1000)
    user_messages = [e.data["message"] for e in events if e.type == EventType.USER_MESSAGE]
    assert any("customers-source" in message for message in user_messages)


@pytest.mark.asyncio
async def test_focused_artifact_revision_supersedes_original(tmp_path: Path) -> None:
    responses = _base_responses() + [
        {
            "reply_to_user": "Updating the poll interval.",
            "requirements_patch": {},
            "next_steps": [
                {
                    "agent": "connect",
                    "instruction": "Revise the orders connector's poll interval",
                    "context_slice": {
                        "revises_artifact_id": "PLACEHOLDER",
                        "name": "orders-source",
                        "config": {"poll.interval.ms": "5000"},
                    },
                    "phase": "connect",
                }
            ],
            "awaiting": "agent:connect",
        },
        {
            "status": "ok",
            "artifacts": [
                {"name": "orders-source", "config": {"poll.interval.ms": "5000"}}
            ],
            "needs_approval": True,
            "warnings": [],
            "summary": "Revised orders-source connector",
        },
    ]
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, _ = await orchestrator.handle_user_message(state, "Move postgres orders into mongo")
    original = state.whiteboard.artifacts[0]
    # The stubbed planner response above can't know the artifact_id ahead of time —
    # patch it in now that we have it, mirroring what a real Planner would receive
    # via focused_artifact.artifact_id in its context.
    orchestrator.llm.responses[0]["next_steps"][0]["context_slice"]["revises_artifact_id"] = (
        original.artifact_id
    )

    state, _ = await orchestrator.handle_user_message(
        state, "change the poll interval on this one", focus_artifact_id=original.artifact_id
    )

    assert original.status == "superseded"
    assert len(state.whiteboard.artifacts) == 2
    revised = state.whiteboard.artifacts[1]
    assert revised.status == "proposed"
    assert revised.content["config"]["poll.interval.ms"] == "5000"


@pytest.mark.asyncio
async def test_planner_failure_is_reported_not_raised(tmp_path: Path) -> None:
    repository = InMemoryStateRepository()
    settings = Settings(deployment_root=tmp_path)
    orchestrator = Orchestrator(_RaisingLLMRouter(), ToolRegistry(), repository, settings)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, reply = await orchestrator.handle_user_message(state, "Move postgres orders into mongo")

    assert "didn't respond" in reply
    assert state.status == "requirements"
    events = await repository.list_events(state.session_id, None, 1000)
    assert any(e.type == EventType.ERROR and e.source == "planner" for e in events)
    # the user's own message is still on record even though the Planner failed
    assert any(e.type == EventType.USER_MESSAGE for e in events)


@pytest.mark.asyncio
async def test_turn_stops_after_max_iterations_instead_of_looping_forever(tmp_path: Path) -> None:
    debug_dispatch = {
        "reply_to_user": "Checking again.",
        "requirements_patch": {},
        "next_steps": [
            {
                "agent": "debug",
                "instruction": "check something",
                "context_slice": {"checks": []},
                "phase": "debug",
            }
        ],
        "awaiting": "agent:debug",
    }
    debug_result = {
        "status": "ok",
        "artifacts": [],
        "needs_approval": False,
        "warnings": [],
        "summary": "nothing new",
    }
    # debug never produces artifacts, so nothing stops the loop except the Planner
    # itself choosing next_steps=[] — here it never does, simulating the observed
    # "keeps re-dispatching forever" behavior.
    responses = [debug_dispatch, debug_result] * 6
    orchestrator, repository = _orchestrator(tmp_path, responses)
    state = SessionState(pipeline_name="orders-pipeline")
    await repository.create_session(state)

    state, reply = await orchestrator.handle_user_message(state, "investigate something")

    assert "Stopped after" in reply
    assert state.status == "requirements"
    events = await repository.list_events(state.session_id, None, 1000)
    assert any(
        e.type == EventType.ERROR and e.data.get("error") == "max_turn_iterations_exceeded"
        for e in events
    )


@pytest.mark.asyncio
async def test_conversation_history_includes_last_ten_plus_starred(tmp_path: Path) -> None:
    orchestrator, repository = _orchestrator(tmp_path, [])
    session_id = "s1"
    base = utc_now()

    # 15 user/assistant turn pairs = 30 events, strictly chronological.
    for i in range(15):
        await repository.add_event(
            SessionEvent(
                session_id=session_id,
                type=EventType.USER_MESSAGE,
                source="user",
                data={"message": f"user turn {i}"},
                created_at=base + timedelta(seconds=i * 2),
            )
        )
        await repository.add_event(
            SessionEvent(
                session_id=session_id,
                type=EventType.AGENT_MESSAGE,
                source="planner",
                data={"reply": f"assistant turn {i}"},
                created_at=base + timedelta(seconds=i * 2 + 1),
            )
        )

    # Star the very first turn — well outside the last-10 window.
    events = await repository.list_events(session_id, None, 1000)
    await repository.set_event_starred(session_id, events[0].event_id, True)

    history = await orchestrator._conversation_history(session_id)

    # 10 most recent turns + 1 starred turn from outside that window.
    assert len(history) == 11
    assert history[0]["content"] == "user turn 0"
    assert history[0]["starred"] is True
    assert history[-1]["content"] == "assistant turn 14"
    assert [turn["created_at"] for turn in history] == sorted(
        turn["created_at"] for turn in history
    )


@pytest.mark.asyncio
async def test_conversation_history_dedupes_starred_message_inside_recent_window(
    tmp_path: Path,
) -> None:
    orchestrator, repository = _orchestrator(tmp_path, [])
    session_id = "s1"
    base = utc_now()

    for i in range(3):
        await repository.add_event(
            SessionEvent(
                session_id=session_id,
                type=EventType.USER_MESSAGE,
                source="user",
                data={"message": f"turn {i}"},
                created_at=base + timedelta(seconds=i),
            )
        )

    events = await repository.list_events(session_id, None, 1000)
    await repository.set_event_starred(session_id, events[-1].event_id, True)  # already recent

    history = await orchestrator._conversation_history(session_id)

    assert len(history) == 3  # not duplicated
