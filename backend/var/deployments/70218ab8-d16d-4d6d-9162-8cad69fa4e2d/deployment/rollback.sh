#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
KSQLDB_URL="${KSQLDB_URL:-http://localhost:8088}"
curl --fail --silent --show-error -X DELETE "$CONNECT_URL/connectors/orders-jdbc-source" || true
printf '%s\n' 'Drop persistent ksqlDB queries and objects explicitly after reviewing dependencies.'
