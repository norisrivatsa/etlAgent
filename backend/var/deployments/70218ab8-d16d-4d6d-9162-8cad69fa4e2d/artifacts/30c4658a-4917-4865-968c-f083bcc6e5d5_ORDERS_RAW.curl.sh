#!/usr/bin/env bash
set -euo pipefail

KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X POST "$KSQLDB_URL/ksql" -H 'Content-Type: application/json' --data-binary @30c4658a-4917-4865-968c-f083bcc6e5d5_ORDERS_RAW.json
