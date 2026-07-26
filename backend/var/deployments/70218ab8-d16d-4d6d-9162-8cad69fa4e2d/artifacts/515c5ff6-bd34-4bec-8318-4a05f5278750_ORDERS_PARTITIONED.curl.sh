#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @515c5ff6-bd34-4bec-8318-4a05f5278750_ORDERS_PARTITIONED.json
