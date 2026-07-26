#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @1facc521-49fc-44b5-bd6b-66d6fd412f60_DAILY_SALES.json
