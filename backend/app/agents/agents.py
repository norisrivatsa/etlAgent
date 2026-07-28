from __future__ import annotations

from typing import Any

from app.agents import base as agents_base
from app.agents.base import WorkerAgent
from app.llm import LLMRouter
from app.models import AgentTask, SessionConfig, WorkerResponse
from app.prompts import load_prompt
from app.tools import ToolRegistry


class PlannerAgent(agents_base.PlannerAgent):
    system_prompt = load_prompt("plannerAgentPrompt.md")


class ConnectAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(load_prompt("connectAgentPrompt.md"), spec)
        return WorkerResponse.model_validate(raw)


class KsqlDBAgent(WorkerAgent):
    """Unlike Connect, this is NOT fanned out per object — ksqlDB objects have an inherent
    dependency order (raw tables before aggregates before joins) that one coherent design
    pass should own, rather than fragmenting across separate Planner-dispatched calls. The
    Planner dispatches exactly one ksqldb next_step per phase; this agent designs the whole
    layered pipeline from the topics the connect phase produced."""

    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(load_prompt("ksqlDBAgentPrompt.md"), spec)
        return WorkerResponse.model_validate(raw)


class EvaluatorAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(load_prompt("evaluatorAgentPrompt.md"), spec)
        return WorkerResponse.model_validate(raw)


class EdgeCaseAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(load_prompt("edgeCaseAgentPrompt.md"), spec)
        return WorkerResponse.model_validate(raw)


class DebugAgent(WorkerAgent):
    async def run(self, task: AgentTask) -> dict[str, Any]:
        context = task.context
        evidence: list[dict[str, Any]] = []
        for check in context.get("checks", []):
            tool = check.get("tool")
            if tool in {"grep", "tail", "journalctl"}:
                result = await self.tools.execute(tool, **check.get("arguments", {}))
                evidence.append({"tool": tool, "result": result})

        raw = await self.ask_json(
            load_prompt("debugAgentPrompt.md"),
            {"request": context, "evidence": evidence},
        )
        response = WorkerResponse.model_validate(raw)
        return response.model_dump(mode="json")


class ExecutorAgent(WorkerAgent):
    """Deploys real infrastructure. Never Planner-dispatchable — only reachable from
    the dedicated /deploy action (see app.orchestrator.PLANNER_DISPATCHABLE_AGENTS)."""

    async def run(self, task: AgentTask) -> dict[str, Any]:
        context = task.context
        records: list[dict[str, Any]] = []
        for connector in context.get("connector_configs", []):
            result = await self.tools.execute(
                "create_connector",
                connect_url=context["connect_url"],
                connector_config=connector,
            )
            records.append({"component": connector.get("name", "connector"), "result": result})
        for statement in context.get("ksql_statements", []):
            result = await self.tools.execute(
                "execute_ksql", ksqldb_url=context["ksqldb_url"], statement=statement
            )
            records.append({"component": "ksql", "result": result})

        response = WorkerResponse(
            status="ok",
            artifacts=[],
            needs_approval=False,
            summary=f"Deployed {len(records)} component(s)",
        )
        result = response.model_dump(mode="json")
        result["records"] = records
        return result


def build_agents(
    config: SessionConfig, llm: LLMRouter, tools: ToolRegistry
) -> dict[str, agents_base.BaseAgent]:
    return {
        "planner": PlannerAgent("planner", config.planner, llm, tools),
        "connect": ConnectAgent("connect", config.connect, llm, tools),
        "ksqldb": KsqlDBAgent("ksqldb", config.ksqldb, llm, tools),
        "evaluator": EvaluatorAgent("evaluator", config.evaluator, llm, tools),
        "edge_case": EdgeCaseAgent("edge_case", config.edge_case, llm, tools),
        "debug": DebugAgent("debug", config.debug, llm, tools),
        "executor": ExecutorAgent("executor", config.executor, llm, tools),
    }
