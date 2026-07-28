from __future__ import annotations

import re
from typing import Any

from app.models import PipelineGraphEdge, PipelineGraphNode, SessionState

# Only artifacts still "live" in the current design belong in the graph — a
# rejected/superseded proposal was thrown out, not part of the pipeline.
_VISIBLE_STATUSES = {"proposed", "committed"}

_CREATE_STREAM_RE = re.compile(r"\bcreate\s+stream\b", re.IGNORECASE)


def _ksql_object_type(content: dict[str, Any]) -> str:
    """content["object_type"] is authoritative when the ksqlDB agent set it;
    fall back to sniffing the statement text for artifacts generated before
    that field existed."""
    declared = content.get("object_type")
    if declared in ("stream", "table"):
        return declared
    statement = content.get("statement", "") or ""
    return "stream" if _CREATE_STREAM_RE.search(statement) else "table"


def build_pipeline_graph(
    state: SessionState,
) -> tuple[list[PipelineGraphNode], list[PipelineGraphEdge]]:
    """Pure, deterministic pipeline-graph construction from committed/proposed
    artifacts and the Planner's own topic declarations (whiteboard.topics) —
    no I/O, no live connector status. See SessionService.connector_status for
    the live piece; the caller merges it onto these nodes afterward."""
    nodes: list[PipelineGraphNode] = []
    edges: list[PipelineGraphEdge] = []
    connector_id_by_name: dict[str, str] = {}
    ksql_id_by_name: dict[str, str] = {}

    live_artifacts = [a for a in state.whiteboard.artifacts if a.status in _VISIBLE_STATUSES]

    for artifact in live_artifacts:
        if artifact.kind != "connector":
            continue
        node_id = f"connector:{artifact.name}"
        connector_id_by_name[artifact.name] = node_id
        node_type = "sink_connector" if artifact.phase == "sink" else "source_connector"
        nodes.append(
            PipelineGraphNode(
                id=node_id,
                name=artifact.name,
                type=node_type,
                artifact_id=artifact.artifact_id,
                phase=artifact.phase,
                status=artifact.status,
            )
        )

    for artifact in live_artifacts:
        if artifact.kind != "ksql_statement":
            continue
        object_name = artifact.content.get("object_name") or artifact.name
        node_id = f"ksql:{object_name}"
        ksql_id_by_name[object_name] = node_id
        node_type = (
            "ksql_stream" if _ksql_object_type(artifact.content) == "stream" else "ksql_table"
        )
        nodes.append(
            PipelineGraphNode(
                id=node_id,
                name=object_name,
                type=node_type,
                artifact_id=artifact.artifact_id,
                phase=artifact.content.get("layer"),
                status=artifact.status,
                statement=artifact.content.get("statement"),
            )
        )

    topic_id_by_name: dict[str, str] = {}
    for topic in state.whiteboard.topics:
        name = topic.get("name")
        if not name or name in topic_id_by_name:
            continue
        node_id = f"topic:{name}"
        topic_id_by_name[name] = node_id
        nodes.append(PipelineGraphNode(id=node_id, name=name, type="topic"))

    # producer -> topic (connector or ksqlDB object that writes to it)
    for topic in state.whiteboard.topics:
        name = topic.get("name")
        produced_by = topic.get("produced_by")
        if not name or not produced_by:
            continue
        target = topic_id_by_name.get(name)
        source = connector_id_by_name.get(produced_by) or ksql_id_by_name.get(produced_by)
        if target and source:
            edges.append(PipelineGraphEdge(source=source, target=target))

    # topic/ksqlDB object -> ksqlDB object (depends_on)
    for artifact in live_artifacts:
        if artifact.kind != "ksql_statement":
            continue
        object_name = artifact.content.get("object_name") or artifact.name
        target = ksql_id_by_name.get(object_name)
        if not target:
            continue
        for upstream in artifact.content.get("depends_on") or []:
            source = (
                topic_id_by_name.get(upstream)
                or ksql_id_by_name.get(upstream)
                or connector_id_by_name.get(upstream)
            )
            if source:
                edges.append(PipelineGraphEdge(source=source, target=target))

    # topic -> sink connector, via the connector config's standard Kafka
    # Connect sink "topics" field (comma-separated topic names).
    for artifact in live_artifacts:
        if artifact.kind != "connector" or artifact.phase != "sink":
            continue
        target = connector_id_by_name.get(artifact.name)
        if not target:
            continue
        topics_config = artifact.content.get("config", {}).get("topics", "") or ""
        for topic_name in (name.strip() for name in topics_config.split(",")):
            source = topic_id_by_name.get(topic_name)
            if source:
                edges.append(PipelineGraphEdge(source=source, target=target))

    return nodes, edges
