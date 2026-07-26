#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
python -c 'import json,sys; print(json.dumps(json.load(open(sys.argv[1])).get("config", {})))' connector_configs/orders-jdbc-source.json | curl --fail --silent --show-error -X PUT "$CONNECT_URL/connectors/orders-jdbc-source/config" -H 'Content-Type: application/json' --data-binary @-
