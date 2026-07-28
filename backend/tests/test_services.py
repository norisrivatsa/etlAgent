from __future__ import annotations

from pathlib import Path

import pytest

from app.config import Settings
from app.llm import StubLLMRouter
from app.models import Artifact, DeploymentStatus, SessionState
from app.orchestrator import Orchestrator
from app.repositories import InMemoryStateRepository
from app.services import SessionService
from app.tools import ToolRegistry, create_tool_registry


def _service(tmp_path: Path, tools: ToolRegistry | None = None) -> SessionService:
    repository = InMemoryStateRepository()
    settings = Settings(deployment_root=tmp_path)
    tools = tools or create_tool_registry(repository, settings)
    llm = StubLLMRouter([])
    orchestrator = Orchestrator(llm, tools, repository, settings)
    return SessionService(repository, orchestrator, llm, tools, settings)


def _committed_connector(name: str) -> Artifact:
    return Artifact(
        agent="connect", kind="connector", name=name, content={}, status="committed", phase="source"
    )


@pytest.mark.asyncio
async def test_connector_statuses_are_grey_before_deployment(tmp_path: Path) -> None:
    service = _service(tmp_path)
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [_committed_connector("orders-source")]
    # deployment_status defaults to state="not_started"

    statuses = await service.connector_statuses(state)

    assert statuses["orders-source"].color == "grey"
    assert statuses["orders-source"].detail == "not deployed yet"


@pytest.mark.asyncio
async def test_connector_statuses_reduce_live_connect_response(tmp_path: Path) -> None:
    class _FakeTools(ToolRegistry):
        async def execute(self, name, **kwargs):
            assert name == "connector_status"
            return {
                "connector": {"state": "RUNNING"},
                "tasks": [{"id": 0, "state": "RUNNING"}, {"id": 1, "state": "FAILED"}],
            }

    service = _service(tmp_path, tools=_FakeTools())
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [_committed_connector("orders-source")]
    state.whiteboard.deployment_status = DeploymentStatus(state="deployed")

    statuses = await service.connector_statuses(state)

    assert statuses["orders-source"].color == "orange"
    assert statuses["orders-source"].failed_tasks == 1
    assert statuses["orders-source"].total_tasks == 2


@pytest.mark.asyncio
async def test_connector_statuses_fall_back_to_grey_on_lookup_failure(tmp_path: Path) -> None:
    class _FailingTools(ToolRegistry):
        async def execute(self, name, **kwargs):
            raise RuntimeError("Connect unreachable")

    service = _service(tmp_path, tools=_FailingTools())
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [_committed_connector("orders-source")]
    state.whiteboard.deployment_status = DeploymentStatus(state="deployed")

    statuses = await service.connector_statuses(state)

    assert statuses["orders-source"].color == "grey"
    assert "Connect unreachable" in statuses["orders-source"].detail


@pytest.mark.asyncio
async def test_pipeline_graph_endpoint_merges_status_onto_connector_nodes(tmp_path: Path) -> None:
    class _FakeTools(ToolRegistry):
        async def execute(self, name, **kwargs):
            return {"connector": {"state": "FAILED"}, "tasks": []}

    service = _service(tmp_path, tools=_FakeTools())
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [_committed_connector("orders-source")]
    state.whiteboard.deployment_status = DeploymentStatus(state="deployed")
    await service.repository.create_session(state)

    graph = await service.pipeline_graph(state.session_id)

    connector_node = next(n for n in graph.nodes if n.id == "connector:orders-source")
    assert connector_node.connector_status.color == "red"
