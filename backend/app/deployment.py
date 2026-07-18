from __future__ import annotations

import json
import shlex
from pathlib import Path
from typing import Any

from app.models import SessionState


class DeploymentPackageBuilder:
    def __init__(self, root: Path):
        self.root = root

    async def build(self, state: SessionState) -> Path:
        package = (self.root / state.session_id / "deployment").resolve()
        connector_dir = package / "connector_configs"
        ksql_dir = package / "ksql"
        connector_dir.mkdir(parents=True, exist_ok=True)
        ksql_dir.mkdir(parents=True, exist_ok=True)

        connectors = state.whiteboard.connectors
        statements = self._statements(state.whiteboard.ksqldb_objects)
        topics = state.whiteboard.topics

        for connector in connectors:
            name = self._safe_name(str(connector.get("name", "connector")))
            await self._write_json(connector_dir / f"{name}.json", connector)

        await self._write(
            ksql_dir / "pipeline.sql",
            "\n\n".join(statement.rstrip(";") + ";" for statement in statements) + "\n",
        )
        await self._write(
            package / "create_topics.sh", self._topic_script(state, topics)
        )
        await self._write(
            package / "deploy_connectors.sh",
            self._connector_script(state, connectors),
        )
        await self._write(package / "deploy_ksql.sh", self._ksql_script(state))
        await self._write(
            package / "rollback.sh", self._rollback_script(state, connectors)
        )
        for script in package.glob("*.sh"):
            script.chmod(0o750)
        return package

    @staticmethod
    def _safe_name(name: str) -> str:
        return "".join(
            char if char.isalnum() or char in "._-" else "_" for char in name
        )

    @staticmethod
    def _statements(objects: list[dict[str, Any]]) -> list[str]:
        statements = []
        for item in objects:
            if isinstance(item, str):
                statements.append(item)
            elif item.get("statement"):
                statements.append(str(item["statement"]))
        return statements

    async def _write(self, path: Path, content: str) -> None:
        path.write_text(content, encoding="utf-8")

    async def _write_json(self, path: Path, value: dict[str, Any]) -> None:
        await self._write(path, json.dumps(value, indent=2, sort_keys=True) + "\n")

    @staticmethod
    def _header() -> str:
        return "#!/usr/bin/env bash\nset -euo pipefail\n\n"

    def _topic_script(self, state: SessionState, topics: list[dict[str, Any]]) -> str:
        bootstrap = (
            f"BOOTSTRAP={shlex.quote(state.config.kafka_bootstrap_servers)}\n"
            if state.config.kafka_bootstrap_servers
            else 'BOOTSTRAP="${KAFKA_BOOTSTRAP_SERVERS:-localhost:9092}"\n'
        )
        lines = [self._header(), bootstrap]
        for topic in topics:
            name = shlex.quote(str(topic["name"]))
            partitions = int(topic.get("partitions", 1))
            replication = int(
                topic.get("replication_factor", topic.get("replication", 1))
            )
            lines.append(
                'kafka-topics.sh --bootstrap-server "$BOOTSTRAP" --create '
                f"--if-not-exists --topic {name} --partitions {partitions} "
                f"--replication-factor {replication}\n"
            )
        return "".join(lines)

    def _connector_script(
        self, state: SessionState, connectors: list[dict[str, Any]]
    ) -> str:
        connect_url = (
            f"CONNECT_URL={shlex.quote(state.config.connect_url)}\n"
            if state.config.connect_url
            else 'CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"\n'
        )
        lines = [self._header(), connect_url]
        for connector in connectors:
            name = self._safe_name(str(connector.get("name", "connector")))
            lines.append(
                "python -c 'import json,sys; "
                'print(json.dumps(json.load(open(sys.argv[1])).get("config", {})))\' '
                f"connector_configs/{name}.json | "
                f"curl --fail --silent --show-error -X PUT "
                f'"$CONNECT_URL/connectors/{name}/config" '
                f"-H 'Content-Type: application/json' "
                f"--data-binary @-\n"
            )
        return "".join(lines)

    def _ksql_script(self, state: SessionState) -> str:
        ksqldb_url = (
            f"KSQLDB_URL={shlex.quote(state.config.ksqldb_url)}\n"
            if state.config.ksqldb_url
            else 'KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"\n'
        )
        return (
            self._header()
            + ksqldb_url
            + "python -c 'import json, pathlib; "
            + 'print(json.dumps({"ksql": pathlib.Path("ksql/pipeline.sql").read_text(), '
            + '"streamsProperties": {}}))\' '
            + '| curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" '
            + "-H 'Content-Type: application/json' --data-binary @-\n"
        )

    def _rollback_script(
        self, state: SessionState, connectors: list[dict[str, Any]]
    ) -> str:
        connect_url = (
            f"CONNECT_URL={shlex.quote(state.config.connect_url)}\n"
            if state.config.connect_url
            else 'CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"\n'
        )
        ksqldb_url = (
            f"KSQLDB_URL={shlex.quote(state.config.ksqldb_url)}\n"
            if state.config.ksqldb_url
            else 'KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"\n'
        )
        lines = [
            self._header(),
            connect_url,
            ksqldb_url,
        ]
        for connector in reversed(connectors):
            name = self._safe_name(str(connector.get("name", "connector")))
            lines.append(
                f"curl --fail --silent --show-error -X DELETE "
                f'"$CONNECT_URL/connectors/{name}" || true\n'
            )
        lines.append(
            "printf '%s\\n' 'Drop persistent ksqlDB queries and objects explicitly "
            "after reviewing dependencies.'\n"
        )
        return "".join(lines)
