from __future__ import annotations

import json
from pathlib import Path

from app.models import Artifact, utc_now


class ArtifactWriter:
    """Pure filesystem code — no LLM call. Writes an approved artifact to disk as a
    curl-able JSON file, matching the curl-template style already used by
    app/deployment.py:DeploymentPackageBuilder."""

    @staticmethod
    def commit(artifact: Artifact, session_id: str, root: Path) -> Artifact:
        directory = root / session_id / "artifacts"
        directory.mkdir(parents=True, exist_ok=True)

        safe_name = "".join(
            char if char.isalnum() or char in "._-" else "_" for char in artifact.name
        )
        json_path = directory / f"{artifact.artifact_id}_{safe_name}.json"
        json_path.write_text(json.dumps(artifact.content, indent=2, sort_keys=True) + "\n")

        curl_path = directory / f"{artifact.artifact_id}_{safe_name}.curl.sh"
        if artifact.kind == "connector":
            body = (
                'CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"\n'
                f"curl --fail --silent --show-error -X PUT "
                f'"$CONNECT_URL/connectors/{safe_name}/config" '
                f"-H 'Content-Type: application/json' "
                f"--data-binary @{json_path.name}\n"
            )
        else:
            body = (
                'KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"\n'
                f'curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" '
                f"-H 'Content-Type: application/json' "
                f"--data-binary @{json_path.name}\n"
            )
        curl_path.write_text(f"#!/usr/bin/env bash\nset -euo pipefail\n\n{body}")
        curl_path.chmod(0o750)

        artifact.status = "committed"
        artifact.file_path = str(json_path)
        artifact.committed_at = utc_now()
        return artifact
