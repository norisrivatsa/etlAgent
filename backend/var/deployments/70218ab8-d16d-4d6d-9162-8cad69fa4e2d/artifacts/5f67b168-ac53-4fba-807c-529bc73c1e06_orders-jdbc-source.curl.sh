#!/usr/bin/env bash
set -euo pipefail

CONNECT_URL="${CONNECT_URL:-http://localhost:8083}"
curl --fail --silent --show-error -X PUT "$CONNECT_URL/connectors/orders-jdbc-source/config" -H 'Content-Type: application/json' --data-binary @5f67b168-ac53-4fba-807c-529bc73c1e06_orders-jdbc-source.json
