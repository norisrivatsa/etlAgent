#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @c5634cac-2d8b-4ef1-8f42-1c4415bfc77a_ORDERS_NORMALIZED.json
