#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @1b1e1c46-bbde-4722-bbfb-1e8be54d14d9_ORDERS_BY_STATUS.json
