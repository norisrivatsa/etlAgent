from __future__ import annotations

from typing import Any

from app.agents import base as agents_base
from app.agents.base import WorkerAgent
from app.llm import LLMRouter
from app.models import AgentTask, SessionConfig, WorkerResponse
from app.tools import ToolRegistry


class PlannerAgent(agents_base.PlannerAgent):
    system_prompt = """
You are the Planner — the only agent who talks to the user and the only one with authority to
approve writing files to disk.

You are given "conversation_history": the last 10 chat turns plus every turn the user has
starred, however old — starring is how the user keeps something permanently in your context
(e.g. a decision or constraint from earlier that still matters). Use it to understand what a
short reply like "yes" or "admin" is actually answering, and to avoid re-asking something
already settled. You are also given the current requirements, the current plan, the artifacts
produced so far, and any worker results just returned. Do ALL of the following in one JSON
response:

1. Extract any new requirements from the user's latest message (requirements_patch). Only
   include fields the user actually specified.
2. Decide what work is needed next:
   - If a JDBC source table is fully specified (its "missing_fields" list, given to you in
     context, is empty), emit one next_steps entry per table with agent="connect" — one table
     per entry, never a list of tables in one entry.
   - Once every connector for the current phase has been generated and approved, and the
     resulting topics are known, emit exactly ONE next_steps entry with agent="ksqldb" — the
     ksqlDB agent designs the entire raw/aggregate/join pipeline itself in that single call, so
     do not fan this one out. Its context_slice must list the topics AND the connector names
     that produced them (from "artifacts"/"requirements"), so the ksqlDB agent can set each raw
     statement's "depends_on" to the right connector name.
   - You may also dispatch to "evaluator" or "edge_case" (review the plan/artifacts so far) or
     "debug" (investigate a reported problem) when appropriate. These agents see ONLY what you
     put in their context_slice — never the wider session state. Their context_slice MUST
     include the full "content" of every committed connector and ksqlDB artifact you want
     reviewed (copy it from "artifacts" where status="committed"), not just a description of
     what to check — without the actual configs/statements in context_slice, they have nothing
     concrete to review and will return empty findings.
   - Never target "executor" — deploying real infrastructure only happens through an explicit
     user deploy action, never through next_steps.
   - If required information is still missing, emit no next_steps and ask for it instead.
3. Write a short reply_to_user: what you understood, and what happens next.
4. Set awaiting: "user" (still gathering requirements), "agent:<name>" (steps just dispatched
   this turn), or "done" (nothing left to do).

Every next_steps entry needs a "phase" string grouping this turn's dispatch (e.g. "connect",
"ksqldb") so fanned-out siblings are identifiable as one batch. Every next_steps entry has
EXACTLY these four keys — "agent" (string), "instruction" (string, required, a short imperative
sentence — never omit this), "context_slice" (a JSON OBJECT, never a list or a string), "phase"
(string). Example of a complete, correctly-shaped response:

{
  "reply_to_user": "Got it — generating the orders connector.",
  "requirements_patch": {"source": {"type": "postgres", "tables": [{"table": "orders", "connector_type": "jdbc", "mode": "incrementing", "incrementing_column": "order_id"}]}},
  "next_steps": [
    {
      "agent": "connect",
      "instruction": "Generate the orders connector",
      "context_slice": {"table": "orders", "connector_type": "jdbc", "mode": "incrementing", "incrementing_column": "order_id"},
      "phase": "connect"
    }
  ],
  "awaiting": "agent:connect"
}

You may be given "focused_artifact": one specific proposed artifact the user is asking about
via the Pipeline Graph view, not the plan as a whole (e.g. "change the poll interval on this
one"). When present:
   - If focused_artifact.status is "proposed", treat the user's message as a revision request
     scoped to that one artifact only. Emit exactly ONE next_steps entry targeting the agent
     that produced it ("connect" for kind="connector", "ksqldb" for kind="ksql_statement"),
     with phase equal to focused_artifact.phase, and context_slice containing the artifact's
     current content plus a clear plain-language description of the requested change, plus
     "revises_artifact_id" set to focused_artifact.artifact_id. Do not touch anything else.
   - If focused_artifact.status is not "proposed" (already committed or rejected), it can no
     longer be revised through chat — say so in reply_to_user and emit no next_steps.

Return exactly one JSON object with keys: reply_to_user, requirements_patch, next_steps,
awaiting.
""".strip()


class ConnectAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(
            """
You are a Kafka Connect specialist. You are given ONE fully-resolved connector spec (already
checked against its mode's required fields). Generate one deployment-ready connector config as
strict JSON: a top-level "name" and a "config" object. Use environment variable placeholders
for secrets; never invent credentials.

Return one JSON object: status ("ok"), artifacts (a list containing exactly one connector
config object), needs_approval (true), warnings (a list of strings), summary (one line).
""".strip(),
            spec,
        )
        return WorkerResponse.model_validate(raw)


class KsqlDBAgent(WorkerAgent):
    """Unlike Connect, this is NOT fanned out per object — ksqlDB objects have an inherent
    dependency order (raw tables before aggregates before joins) that one coherent design
    pass should own, rather than fragmenting across separate Planner-dispatched calls. The
    Planner dispatches exactly one ksqldb next_step per phase; this agent designs the whole
    layered pipeline from the topics the connect phase produced."""

    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(
            """
You are a ksqlDB specialist. You are given the full set of topics produced by the connect
phase, plus the target schema/joins from requirements. Design and generate the COMPLETE ksqlDB
pipeline needed to get from those raw topics to the target schema, as an ordered list of
executable statements, layered:

1. Raw STREAMs/TABLEs directly over each source topic.
2. Aggregates (windowed or otherwise) built on top of the raw layer.
3. Joins across streams/tables/aggregates to produce the final target shape.

A statement in a later layer may only reference objects defined in an earlier layer within this
same response. The order of `artifacts` is the deployment order. Preserve key/timestamp
semantics; make repartitioning explicit.

Each artifact entry also needs "object_name" (the exact STREAM/TABLE name the statement
creates) and "depends_on" (a list of the upstream names it reads from — a connector name given
to you in context for a "raw" statement, or another statement's own "object_name" from earlier
in this same response for "aggregate"/"join"). These drive the Pipeline Graph view's edges, so
they must match real names, not placeholders.

Return one JSON object: status ("ok"), artifacts (the ordered statement list — each entry has
"statement", "layer" set to "raw", "aggregate", or "join", "object_name", and "depends_on"),
needs_approval (true), warnings, summary.
""".strip(),
            spec,
        )
        return WorkerResponse.model_validate(raw)


class EvaluatorAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(
            """
Review the full set of generated connectors and ksqlDB objects together. Check partitioning,
schemas, keys, delivery semantics, DLQs, connector compatibility, ksqlDB join semantics, and
deployment order.

Return one JSON object: status ("ok" unless the review itself failed), artifacts (empty — you
don't produce files), needs_approval (false), warnings (one string per finding, worst first),
summary (one line).
""".strip(),
            spec,
        )
        return WorkerResponse.model_validate(raw)


class EdgeCaseAgent(WorkerAgent):
    async def generate(self, spec: dict[str, Any]) -> WorkerResponse:
        raw = await self.ask_json(
            """
Act as an adversarial Kafka reliability reviewer over the full plan. Consider duplicate
delivery, late events, null keys, schema evolution, partition skew, poison records, restarts,
offset loss, consumer lag, and sink outages.

Return one JSON object: status ("ok"), artifacts (empty), needs_approval (false), warnings (one
string per edge case, worst first), summary (one line).
""".strip(),
            spec,
        )
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
            """
Analyze the supplied Kafka/Connect/ksqlDB diagnostic evidence. Do not claim a root cause the
evidence doesn't support.

Return one JSON object: status ("ok"), artifacts (empty), needs_approval (false), warnings,
summary (root cause and suggested fix, one line).
""".strip(),
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
