from __future__ import annotations

import asyncio
import json
from abc import ABC, abstractmethod
from typing import Any

import httpx

from app.llm import LLMRouter
from app.models import (
    AgentModelConfig,
    AgentTask,
    PlannerLLMOutput,
    SessionConfig,
    VerificationCheck,
)
from app.tools import ToolRegistry


class BaseAgent(ABC):
    def __init__(
        self,
        name: str,
        model_config: AgentModelConfig,
        llm: LLMRouter,
        tools: ToolRegistry,
    ):
        self.name = name
        self.model_config = model_config
        self.llm = llm
        self.tools = tools

    async def ask_json(
        self, system_prompt: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return await self.llm.generate_json(
            self.model_config,
            system_prompt,
            json.dumps(payload, indent=2, default=str),
        )

    @abstractmethod
    async def run(self, task: AgentTask) -> dict[str, Any]: ...


class PlannerAgent(BaseAgent):
    async def run(self, task: AgentTask) -> dict[str, Any]:
        result = await self.ask_json(
            """
You are the owner and architect of a stateful Kafka pipeline design session.
Extract requirements from the user's latest message, update only supplied fields,
maintain a concrete plan, and ask focused questions for missing information.
Set ready_for_approval only when source, sink, topics/data flow, delivery semantics,
failure handling, and any joins are sufficiently specified.
Return one JSON object with: reply, requirements_patch, plan, open_questions,
ready_for_approval. The plan has summary, topics, connectors, ksqldb_objects,
dependencies, and deployment_order.
""".strip(),
            task.context,
        )
        return PlannerLLMOutput.model_validate(result).model_dump(mode="json")


class StructuredWorkerAgent(BaseAgent):
    system_prompt: str

    async def run(self, task: AgentTask) -> dict[str, Any]:
        return await self.ask_json(self.system_prompt, task.context)


class ConnectAgent(StructuredWorkerAgent):
    system_prompt = """
You are a Kafka Connect specialist. Generate deployment-ready source and sink
connector configurations as strict JSON. Include connector_configs, dlq_configs,
and warnings. Each connector must have a top-level name and config object. Use
environment variable placeholders for secrets; never invent credentials.
""".strip()


class KsqlDBAgent(StructuredWorkerAgent):
    system_prompt = """
You are a ksqlDB specialist. Generate ordered, executable statements for streams,
tables, joins, windows, and INSERT/CSAS/CTAS operations. Return JSON with
statements (a list of SQL strings), objects, and warnings. Preserve key and
timestamp semantics and make repartitioning explicit.
""".strip()


class EvaluatorAgent(StructuredWorkerAgent):
    system_prompt = """
Review the Kafka pipeline plan and generated artifacts. Return JSON containing
findings, approved, and summary. Every finding must include severity, component,
issue, and remediation. Check partitioning, schemas, keys, delivery semantics,
DLQs, connector compatibility, ksqlDB join semantics, deployment order, security,
and operability. approved is false for unresolved high or critical findings.
""".strip()


class EdgeCaseAgent(StructuredWorkerAgent):
    system_prompt = """
Act as an adversarial Kafka reliability reviewer. Return JSON with edge_cases and
summary. Each edge case includes severity, scenario, impact, detection, and
mitigation. Cover duplicate delivery, late events, null keys, schema evolution,
partition skew, poison records, restarts, offset loss, lag, sink outages, and
state-store recovery as relevant to this plan.
""".strip()


class ExecutorAgent(BaseAgent):
    async def run(self, task: AgentTask) -> dict[str, Any]:
        context = task.context
        records: list[dict[str, Any]] = []
        for connector in context.get("connector_configs", []):
            try:
                result = await self.tools.execute(
                    "create_connector",
                    connect_url=context["connect_url"],
                    connector_config=connector,
                )
                records.append(
                    {
                        "component": connector.get("name", "connector"),
                        "type": "connector",
                        "status": "deployed",
                        "result": result,
                    }
                )
            except Exception as exc:
                records.append(
                    {
                        "component": connector.get("name", "connector"),
                        "type": "connector",
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                return {"success": False, "records": records}

        for index, statement in enumerate(context.get("ksql_statements", []), start=1):
            try:
                result = await self.tools.execute(
                    "execute_ksql",
                    ksqldb_url=context["ksqldb_url"],
                    statement=statement,
                )
                records.append(
                    {
                        "component": f"ksql-{index}",
                        "type": "ksql",
                        "status": "deployed",
                        "result": result,
                    }
                )
            except Exception as exc:
                records.append(
                    {
                        "component": f"ksql-{index}",
                        "type": "ksql",
                        "status": "failed",
                        "error": str(exc),
                    }
                )
                return {"success": False, "records": records}
        return {"success": True, "records": records}


class DebugAgent(BaseAgent):
    async def run(self, task: AgentTask) -> dict[str, Any]:
        context = task.context
        evidence: list[dict[str, Any]] = []
        for check in context.get("checks", []):
            tool = check.get("tool")
            if tool not in {"grep", "tail", "journalctl", "connector_status"}:
                continue
            try:
                result = await self.tools.execute(tool, **check.get("arguments", {}))
            except Exception as exc:
                result = {"success": False, "error": str(exc)}
            evidence.append({"tool": tool, "result": result})
        analysis = await self.ask_json(
            """
Analyze the supplied Kafka, Connect, and ksqlDB diagnostic evidence. Return JSON
with root_cause, severity, evidence, remediation, and next_checks. Do not claim a
root cause that is not supported by evidence.
""".strip(),
            {"request": context, "evidence": evidence},
        )
        analysis["raw_evidence"] = evidence
        return analysis


class VerificationAgent(BaseAgent):
    async def run(self, task: AgentTask) -> dict[str, Any]:
        context = task.context
        checks: list[VerificationCheck] = []

        for connector in context.get("connectors", []):
            name = connector.get("name")
            try:
                status = await self.tools.execute(
                    "connector_status",
                    connect_url=context["connect_url"],
                    connector_name=name,
                )
                connector_state = status.get("connector", {}).get("state")
                tasks_running = all(
                    item.get("state") == "RUNNING" for item in status.get("tasks", [])
                )
                passed = connector_state == "RUNNING" and tasks_running
                checks.append(
                    VerificationCheck(
                        name=f"connector:{name}",
                        passed=passed,
                        status="passed" if passed else "failed",
                        details=status,
                    )
                )
            except Exception as exc:
                checks.append(
                    VerificationCheck(
                        name=f"connector:{name}",
                        passed=False,
                        status="error",
                        details={"error": str(exc)},
                    )
                )

        offset_results: dict[str, dict[str, Any]] = {}
        topics = set(context.get("expected_topic_counts", {}))
        topics.update(
            item.get("name") for item in context.get("topics", []) if item.get("name")
        )
        for topic in sorted(topics):
            first = await self.tools.execute(
                "topic_offsets",
                bootstrap_servers=context["bootstrap_servers"],
                topic=topic,
            )
            await asyncio.sleep(context.get("offset_sample_seconds", 2))
            second = await self.tools.execute(
                "topic_offsets",
                bootstrap_servers=context["bootstrap_servers"],
                topic=topic,
            )
            offset_results[topic] = {"first": first, "second": second}
            expected = context.get("expected_topic_counts", {}).get(topic)
            count = second.get("count")
            count_ok = count is not None and (expected is None or count >= expected)
            checks.append(
                VerificationCheck(
                    name=f"topic_records:{topic}",
                    passed=count_ok,
                    status="passed" if count_ok else "failed",
                    details={"count": count, "expected_minimum": expected},
                )
            )
            advancing = (
                first.get("count") is not None
                and second.get("count") is not None
                and second["count"] > first["count"]
            )
            checks.append(
                VerificationCheck(
                    name=f"offsets_advancing:{topic}",
                    passed=advancing,
                    status="passed" if advancing else "not_observed",
                    details=offset_results[topic],
                )
            )

        await self._check_sink(context, checks)
        await self._check_query(
            "duplicates", context.get("duplicate_check_query"), context, checks
        )
        await self._check_query(
            "joins", context.get("join_check_query"), context, checks
        )
        required = [check for check in checks if check.status not in {"not_configured"}]
        return {
            "success": bool(required)
            and all(check.passed is not False for check in required),
            "checks": [check.model_dump(mode="json") for check in checks],
        }

    async def _check_sink(
        self, context: dict[str, Any], checks: list[VerificationCheck]
    ) -> None:
        url = context.get("sink_count_url")
        expected = context.get("expected_sink_count")
        if not url:
            checks.append(VerificationCheck(name="sink_count", status="not_configured"))
            return
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url)
                response.raise_for_status()
                payload = response.json()
            count = payload.get("count") if isinstance(payload, dict) else None
            passed = count is not None and (expected is None or count == expected)
            checks.append(
                VerificationCheck(
                    name="sink_count",
                    passed=passed,
                    status="passed" if passed else "failed",
                    details={"count": count, "expected": expected},
                )
            )
        except Exception as exc:
            checks.append(
                VerificationCheck(
                    name="sink_count",
                    passed=False,
                    status="error",
                    details={"error": str(exc)},
                )
            )

    async def _check_query(
        self,
        name: str,
        statement: str | None,
        context: dict[str, Any],
        checks: list[VerificationCheck],
    ) -> None:
        if not statement:
            checks.append(VerificationCheck(name=name, status="not_configured"))
            return
        try:
            rows = await self.tools.execute(
                "query_ksql",
                ksqldb_url=context["ksqldb_url"],
                statement=statement,
            )
            data_rows = [row for row in rows if "row" in row]
            passed = len(data_rows) == 0 if name == "duplicates" else len(data_rows) > 0
            checks.append(
                VerificationCheck(
                    name=name,
                    passed=passed,
                    status="passed" if passed else "failed",
                    details={"rows": data_rows[:20]},
                )
            )
        except Exception as exc:
            checks.append(
                VerificationCheck(
                    name=name,
                    passed=False,
                    status="error",
                    details={"error": str(exc)},
                )
            )


def build_agents(
    config: SessionConfig, llm: LLMRouter, tools: ToolRegistry
) -> dict[str, BaseAgent]:
    return {
        "planner": PlannerAgent("planner", config.planner, llm, tools),
        "connect": ConnectAgent("connect", config.connect, llm, tools),
        "ksqldb": KsqlDBAgent("ksqldb", config.ksqldb, llm, tools),
        "evaluator": EvaluatorAgent("evaluator", config.evaluator, llm, tools),
        "edge_case": EdgeCaseAgent("edge_case", config.edge_case, llm, tools),
        "executor": ExecutorAgent("executor", config.executor, llm, tools),
        "debug": DebugAgent("debug", config.debug, llm, tools),
        "verification": VerificationAgent(
            "verification", config.verification, llm, tools
        ),
    }
