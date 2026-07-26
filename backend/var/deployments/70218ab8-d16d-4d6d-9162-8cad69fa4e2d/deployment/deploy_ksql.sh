#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
python -c 'import json, pathlib; print(json.dumps({"ksql": pathlib.Path("ksql/pipeline.sql").read_text(), "streamsProperties": {}}))' | curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @-
