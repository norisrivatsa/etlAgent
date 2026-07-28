from __future__ import annotations

from app.models import Artifact, SessionState, TopicDeclaration
from app.orchestrator import Orchestrator
from app.pipeline_graph import build_pipeline_graph


def _connector(name: str, phase: str, status: str = "committed", config: dict | None = None) -> Artifact:
    return Artifact(
        agent="connect",
        kind="connector",
        name=name,
        content={"name": name, "config": config or {}},
        status=status,
        phase=phase,
    )


def _ksql(
    object_name: str,
    layer: str,
    object_type: str,
    depends_on: list[str],
    status: str = "committed",
) -> Artifact:
    return Artifact(
        agent="ksqldb",
        kind="ksql_statement",
        name=object_name,
        content={
            "statement": f"CREATE {object_type.upper()} {object_name} ...",
            "layer": layer,
            "object_name": object_name,
            "object_type": object_type,
            "depends_on": depends_on,
        },
        status=status,
        phase="ksqldb",
    )


def test_full_pipeline_topology_matches_source_to_sink() -> None:
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [
        _connector("orders-source", "source"),
        _ksql("ORDERS_STREAM", "raw", "stream", ["orders.orders"]),
        _ksql("FINAL_JOINED_TABLE", "join", "table", ["ORDERS_STREAM"]),
        _connector("mongo-sink", "sink", config={"topics": "final.joined.topic"}),
    ]
    Orchestrator._upsert_topics(
        state,
        [
            TopicDeclaration(name="orders.orders", produced_by="orders-source"),
            TopicDeclaration(name="final.joined.topic", produced_by="FINAL_JOINED_TABLE"),
        ],
    )

    nodes, edges = build_pipeline_graph(state)
    by_id = {node.id: node for node in nodes}

    assert by_id["connector:orders-source"].type == "source_connector"
    assert by_id["connector:mongo-sink"].type == "sink_connector"
    assert by_id["topic:orders.orders"].type == "topic"
    assert by_id["topic:final.joined.topic"].type == "topic"
    assert by_id["ksql:ORDERS_STREAM"].type == "ksql_stream"
    assert by_id["ksql:FINAL_JOINED_TABLE"].type == "ksql_table"
    assert by_id["ksql:FINAL_JOINED_TABLE"].statement == "CREATE TABLE FINAL_JOINED_TABLE ..."

    edge_pairs = {(edge.source, edge.target) for edge in edges}
    assert edge_pairs == {
        ("connector:orders-source", "topic:orders.orders"),
        ("topic:orders.orders", "ksql:ORDERS_STREAM"),
        ("ksql:ORDERS_STREAM", "ksql:FINAL_JOINED_TABLE"),
        ("ksql:FINAL_JOINED_TABLE", "topic:final.joined.topic"),
        ("topic:final.joined.topic", "connector:mongo-sink"),
    }


def test_ksql_object_type_falls_back_to_statement_text_when_missing() -> None:
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [
        Artifact(
            agent="ksqldb",
            kind="ksql_statement",
            name="LEGACY_STREAM",
            content={
                "statement": "CREATE STREAM LEGACY_STREAM AS SELECT * FROM x;",
                "layer": "raw",
                "object_name": "LEGACY_STREAM",
                "depends_on": [],
                # no object_type -- simulates an artifact from before the field existed
            },
            status="committed",
            phase="ksqldb",
        )
    ]

    nodes, _ = build_pipeline_graph(state)
    assert nodes[0].type == "ksql_stream"


def test_rejected_and_superseded_artifacts_are_excluded() -> None:
    state = SessionState(pipeline_name="p")
    state.whiteboard.artifacts = [
        _connector("rejected-connector", "source", status="rejected"),
        _connector("superseded-connector", "source", status="superseded"),
        _connector("live-connector", "source", status="proposed"),
    ]

    nodes, _ = build_pipeline_graph(state)
    names = {node.name for node in nodes}
    assert names == {"live-connector"}


def test_topics_upsert_by_name_does_not_duplicate() -> None:
    state = SessionState(pipeline_name="p")
    Orchestrator._upsert_topics(
        state, [TopicDeclaration(name="orders.orders", produced_by="orders-source")]
    )
    Orchestrator._upsert_topics(
        state, [TopicDeclaration(name="orders.orders", produced_by="orders-source-v2")]
    )

    assert state.whiteboard.topics == [
        {"name": "orders.orders", "produced_by": "orders-source-v2"}
    ]
