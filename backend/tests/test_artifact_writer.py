from __future__ import annotations

from pathlib import Path

from app.artifact_writer import ArtifactWriter
from app.models import Artifact


def _curl_path_for(json_path: Path) -> Path:
    return json_path.with_name(json_path.name.replace(".json", ".curl.sh"))


def test_commit_writes_json_and_executable_curl_script(tmp_path: Path) -> None:
    artifact = Artifact(
        agent="connect",
        kind="connector",
        name="orders-source",
        content={
            "name": "orders-source",
            "config": {"connector.class": "JdbcSourceConnector"},
        },
    )

    committed = ArtifactWriter.commit(artifact, "session-1", tmp_path)

    assert committed.status == "committed"
    assert committed.committed_at is not None
    assert committed.file_path is not None

    json_path = Path(committed.file_path)
    assert json_path.is_file()
    assert "JdbcSourceConnector" in json_path.read_text()

    curl_path = _curl_path_for(json_path)
    assert curl_path.is_file()
    assert curl_path.stat().st_mode & 0o100  # owner-executable bit set
    assert "curl" in curl_path.read_text()
    assert "-X PUT" in curl_path.read_text()


def test_commit_uses_post_for_ksql_statements(tmp_path: Path) -> None:
    artifact = Artifact(
        agent="ksqldb",
        kind="ksql_statement",
        name="raw_0",
        content={"statement": "CREATE STREAM x ...;", "layer": "raw"},
    )

    committed = ArtifactWriter.commit(artifact, "session-1", tmp_path)

    curl_path = _curl_path_for(Path(committed.file_path))
    body = curl_path.read_text()
    assert "-X POST" in body
    assert "/ksql" in body
