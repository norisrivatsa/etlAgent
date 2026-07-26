from __future__ import annotations

import pytest

from app.agents.agents import (
    ConnectAgent,
    DebugAgent,
    EdgeCaseAgent,
    EvaluatorAgent,
    ExecutorAgent,
    KsqlDBAgent,
    PlannerAgent,
)
from app.llm import StubLLMRouter
from app.models import AgentModelConfig, AgentTask, PlannerResponse, WorkerResponse
from app.tools import ToolRegistry

MODEL_CONFIG = AgentModelConfig()


def _task(agent: str, context: dict) -> AgentTask:
    return AgentTask(session_id="s1", agent=agent, instruction="do it", context=context)


@pytest.mark.asyncio
async def test_planner_agent_returns_valid_planner_response() -> None:
    llm = StubLLMRouter(
        [
            {
                "reply_to_user": "Got it.",
                "requirements_patch": {"source": {"type": "postgres"}},
                "next_steps": [
                    {
                        "agent": "connect",
                        "instruction": "make it",
                        "context_slice": {"table": "orders"},
                        "phase": "connect",
                    }
                ],
                "awaiting": "agent:connect",
            }
        ]
    )
    agent = PlannerAgent("planner", MODEL_CONFIG, llm, ToolRegistry())

    result = await agent.run(_task("planner", {"user_message": "postgres orders to mongo"}))

    response = PlannerResponse.model_validate(result)
    assert response.awaiting == "agent:connect"
    assert response.next_steps[0].agent == "connect"


@pytest.mark.asyncio
async def test_connect_agent_returns_valid_worker_response() -> None:
    llm = StubLLMRouter(
        [
            {
                "status": "ok",
                "artifacts": [
                    {"name": "orders-source", "config": {"connector.class": "JdbcSourceConnector"}}
                ],
                "needs_approval": True,
                "warnings": [],
                "summary": "Generated orders-source connector",
            }
        ]
    )
    agent = ConnectAgent("connect", MODEL_CONFIG, llm, ToolRegistry())

    result = await agent.run(_task("connect", {"table": "orders"}))

    response = WorkerResponse.model_validate(result)
    assert response.status == "ok"
    assert response.needs_approval is True
    assert response.artifacts[0]["name"] == "orders-source"


@pytest.mark.asyncio
async def test_ksqldb_agent_returns_layered_pipeline() -> None:
    llm = StubLLMRouter(
        [
            {
                "status": "ok",
                "artifacts": [
                    {"statement": "CREATE STREAM orders_raw ...;", "layer": "raw"},
                    {"statement": "CREATE TABLE orders_agg ...;", "layer": "aggregate"},
                    {"statement": "CREATE STREAM orders_joined ...;", "layer": "join"},
                ],
                "needs_approval": True,
                "warnings": [],
                "summary": "Full pipeline",
            }
        ]
    )
    agent = KsqlDBAgent("ksqldb", MODEL_CONFIG, llm, ToolRegistry())

    result = await agent.run(_task("ksqldb", {"topics": ["orders.orders"]}))

    response = WorkerResponse.model_validate(result)
    layers = [item["layer"] for item in response.artifacts]
    assert layers == ["raw", "aggregate", "join"]


@pytest.mark.asyncio
async def test_evaluator_agent_reports_findings() -> None:
    llm = StubLLMRouter(
        [
            {
                "status": "ok",
                "artifacts": [],
                "needs_approval": False,
                "warnings": ["partition mismatch"],
                "summary": "One finding.",
            }
        ]
    )
    agent = EvaluatorAgent("evaluator", MODEL_CONFIG, llm, ToolRegistry())

    result = await agent.run(_task("evaluator", {"artifacts": []}))

    response = WorkerResponse.model_validate(result)
    assert response.warnings == ["partition mismatch"]
    assert response.needs_approval is False


@pytest.mark.asyncio
async def test_edge_case_agent_reports_edge_cases() -> None:
    llm = StubLLMRouter(
        [
            {
                "status": "ok",
                "artifacts": [],
                "needs_approval": False,
                "warnings": ["duplicate delivery risk"],
                "summary": "One edge case.",
            }
        ]
    )
    agent = EdgeCaseAgent("edge_case", MODEL_CONFIG, llm, ToolRegistry())

    result = await agent.run(_task("edge_case", {"plan": {}}))

    response = WorkerResponse.model_validate(result)
    assert response.warnings == ["duplicate delivery risk"]


@pytest.mark.asyncio
async def test_debug_agent_calls_tools_then_llm() -> None:
    calls = []

    async def fake_grep(**kwargs):
        calls.append(("grep", kwargs))
        return {"success": True, "matches": "ERROR: connector timeout"}

    tools = ToolRegistry()
    tools.register("grep", fake_grep)

    llm = StubLLMRouter(
        [
            {
                "status": "ok",
                "artifacts": [],
                "needs_approval": False,
                "warnings": [],
                "summary": "Root cause: connector timeout.",
            }
        ]
    )
    agent = DebugAgent("debug", MODEL_CONFIG, llm, tools)

    result = await agent.run(
        _task(
            "debug",
            {
                "checks": [
                    {
                        "tool": "grep",
                        "arguments": {"pattern": "ERROR", "file_path": "/var/log/connect.log"},
                    }
                ]
            },
        )
    )

    response = WorkerResponse.model_validate(result)
    assert calls[0][0] == "grep"
    assert "timeout" in response.summary


@pytest.mark.asyncio
async def test_executor_agent_deploys_via_tools() -> None:
    created = []

    async def fake_create_connector(**kwargs):
        created.append(kwargs["connector_config"]["name"])
        return {"name": kwargs["connector_config"]["name"]}

    async def fake_execute_ksql(**kwargs):
        created.append("ksql")
        return {"ok": True}

    tools = ToolRegistry()
    tools.register("create_connector", fake_create_connector)
    tools.register("execute_ksql", fake_execute_ksql)

    agent = ExecutorAgent("executor", MODEL_CONFIG, StubLLMRouter(), tools)

    result = await agent.run(
        _task(
            "executor",
            {
                "connect_url": "http://connect",
                "ksqldb_url": "http://ksqldb",
                "connector_configs": [{"name": "orders-source", "config": {}}],
                "ksql_statements": ["CREATE STREAM x ...;"],
            },
        )
    )

    assert created == ["orders-source", "ksql"]
    assert result["status"] == "ok"
    assert len(result["records"]) == 2
