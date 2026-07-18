from __future__ import annotations

import json

from base_agents import (
    ServiceAgent,
    ThinkingAgent,
)
from models import (
    AgentTask,
)

# ==========================================================
# PLANNER
# ==========================================================


class PlannerAgent(ThinkingAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        session_id = task.context_slice["session_id"]

        whiteboard = await self.read_whiteboard(session_id)

        prompt = f"""
Current Whiteboard:

{json.dumps(whiteboard, indent=2)}

Return JSON:

{{
  "observation":"",
  "reasoning":"",
  "action":"",
  "agent":"",
  "instruction":""
}}
"""

        response = await self.llm.generate(
            system_prompt="""
You are the Planner Agent.

You own the whiteboard.

Determine next action.
""",
            user_prompt=prompt,
            json_mode=True,
        )

        result = json.loads(response)

        await self.complete_task(
            task.task_id,
            result,
        )

        return result


# ==========================================================
# EVALUATOR
# ==========================================================


class EvaluatorAgent(ThinkingAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        prompt = f"""
Review pipeline.

Context:

{json.dumps(task.context_slice, indent=2)}

Return JSON findings.
"""

        response = await self.llm.generate(
            system_prompt="""
You are a Kafka evaluator.

Review:

- scale
- schemas
- joins
- dlq
- partitions
""",
            user_prompt=prompt,
            json_mode=True,
        )

        result = json.loads(response)

        await self.complete_task(
            task.task_id,
            result,
        )

        return result


# ==========================================================
# EDGE CASE
# ==========================================================


class EdgeCaseAgent(ThinkingAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        response = await self.llm.generate(
            system_prompt="""
Generate realistic Kafka edge cases.

Return JSON.
""",
            user_prompt=json.dumps(
                task.context_slice,
                indent=2,
            ),
            json_mode=True,
        )

        result = json.loads(response)

        await self.complete_task(
            task.task_id,
            result,
        )

        return result


# ==========================================================
# CONNECT
# ==========================================================


class ConnectAgent(ServiceAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        prompt = f"""
Generate Kafka Connect configs.

Context:

{json.dumps(task.context_slice, indent=2)}

Return JSON.
"""

        response = await self.llm.generate(
            system_prompt="""
You are a Kafka Connect expert.

Generate:

- source configs
- sink configs
- SMTs
- DLQ
""",
            user_prompt=prompt,
            json_mode=True,
        )

        result = json.loads(response)

        await self.complete_task(
            task.task_id,
            result,
        )

        return result


# ==========================================================
# KSQLDB
# ==========================================================


class KsqlDBAgent(ServiceAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        prompt = f"""
Generate ksqlDB statements.

Context:

{json.dumps(task.context_slice, indent=2)}
"""

        response = await self.llm.generate(
            system_prompt="""
You are a ksqlDB expert.

Generate:

- streams
- tables
- joins
- windows
- inserts

Return JSON.
""",
            user_prompt=prompt,
            json_mode=True,
        )

        result = json.loads(response)

        await self.complete_task(
            task.task_id,
            result,
        )

        return result


# ==========================================================
# EXECUTOR
# ==========================================================


class ExecutorAgent(ServiceAgent):
    async def run(
        self,
        task: AgentTask,
    ):

        context = task.context_slice

        deployment_log = []

        connect_url = context.get("connect_url")

        ksqldb_url = context.get("ksqldb_url")

        connectors = context.get("connector_configs", [])

        statements = context.get("ksql_statements", [])

        for connector in connectors:
            result = await self.tools.execute(
                "create_connector",
                connect_url=connect_url,
                connector_config=connector,
            )

            deployment_log.append(
                {
                    "type": "connector",
                    "result": result,
                }
            )

        for statement in statements:
            result = await self.tools.execute(
                "execute_ksql",
                ksqldb_url=ksqldb_url,
                statement=statement,
            )

            deployment_log.append(
                {
                    "type": "ksql",
                    "result": result,
                }
            )

        await self.complete_task(
            task.task_id,
            {"deployment_log": deployment_log},
        )

        return deployment_log


# ==========================================================
# DEBUG
# ==========================================================


class DebugAgent(ServiceAgent):
    CONNECT_LOG = "/var/log/kafka-stack/connect/connect.log"

    KSQL_LOG = "/var/log/kafka-stack/ksqldb/ksqldb.log"

    KAFKA_LOG = "/var/log/kafka-stack/kafka/server.log"

    async def run(
        self,
        task: AgentTask,
    ):

        findings = []

        grep_errors = await self.tools.execute(
            "grep",
            pattern="ERROR",
            file_path=self.CONNECT_LOG,
        )

        findings.append({"errors": grep_errors})

        tail_logs = await self.tools.execute(
            "tail",
            file_path=self.CONNECT_LOG,
            lines=200,
        )

        findings.append({"tail": tail_logs})

        prompt = f"""
Analyze logs.

{json.dumps(findings, indent=2)}

Return:

{{
  "root_cause":"",
  "fix":"",
  "severity":""
}}
"""

        response = await self.llm.generate(
            system_prompt="""
You are a Kafka debugging expert.
""",
            user_prompt=prompt,
            json_mode=True,
        )

        result = json.loads(response)

        await self.tools.execute(
            "add_context",
            context={
                "task_id": task.task_id,
                "from_agent": "debug",
                "to_agent": "connect",
                "message": result.get(
                    "fix",
                    "",
                ),
                "context_type": "finding",
            },
        )

        await self.complete_task(
            task.task_id,
            result,
        )

        return result
