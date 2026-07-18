#!/bin/bash
# =============================================================================
# Start Script — Kafka Stack
# Order: Kafka → Connect internal topics → Connect → ksqlDB
# =============================================================================

set -euo pipefail

KAFKA_DIR="/opt/kafka-stack/kafka"
KSQLDB_DIR="/opt/kafka-stack/ksqldb"
CONFIGS="/opt/kafka-stack/configs"
LOGS="/var/log/kafka-stack"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
info()    { echo -e "${GREEN}[INFO]${NC}    $1"; }
warn()    { echo -e "${YELLOW}[WARN]${NC}    $1"; }
waiting() { echo -e "${YELLOW}[WAITING]${NC} $1"; }

wait_for_port() {
  local port=$1 service=$2 retries=30
  waiting "Waiting for $service on port $port..."
  for i in $(seq 1 $retries); do
    nc -z localhost "$port" 2>/dev/null && { info "$service is up"; return 0; }
    sleep 2
  done
  echo -e "${RED}[ERROR]${NC} $service failed to start on port $port"
  exit 1
}

# ---------- 1. KAFKA BROKER ----------
info "Starting Kafka (KRaft mode)..."
"$KAFKA_DIR/bin/kafka-server-start.sh" -daemon \
  "$CONFIGS/kafka-kraft.properties"

wait_for_port 9092 "Kafka Broker"

# ---------- 2. CREATE INTERNAL CONNECT TOPICS ----------
# auto.create.topics.enable=false on broker, so we create Connect internals manually
info "Creating Kafka Connect internal topics..."

create_topic() {
  local topic=$1 partitions=$2 config=$3
  "$KAFKA_DIR/bin/kafka-topics.sh" \
    --bootstrap-server localhost:9092 \
    --create --if-not-exists \
    --topic "$topic" \
    --partitions "$partitions" \
    --replication-factor 1 \
    --config "$config" 2>/dev/null \
    && info "  Topic created: $topic" \
    || info "  Topic exists:  $topic"
}

create_topic "_connect-configs"  1 "cleanup.policy=compact"
create_topic "_connect-offsets"  3 "cleanup.policy=compact"
create_topic "_connect-status"   3 "cleanup.policy=compact"

# ---------- 3. KAFKA CONNECT ----------
info "Starting Kafka Connect (distributed mode)..."
"$KAFKA_DIR/bin/connect-distributed.sh" \
  "$CONFIGS/connect-distributed.properties" \
  > "$LOGS/connect/connect.log" 2>&1 &
echo $! > /tmp/kafka-connect.pid

wait_for_port 8083 "Kafka Connect"

# ---------- 4. KSQLDB ----------
info "Starting ksqlDB..."
"$KSQLDB_DIR/bin/ksql-server-start" \
  "$CONFIGS/ksqldb-server.properties" \
  > "$LOGS/ksqldb/ksqldb.log" 2>&1 &
echo $! > /tmp/ksqldb.pid

wait_for_port 8088 "ksqlDB"

# ---------- DONE ----------
echo ""
info "=============================================="
info " All services running:"
info "  Kafka Broker  : localhost:9092"
info "  Kafka Connect : localhost:8083  (REST API)"
info "  ksqlDB        : localhost:8088  (REST API)"
info "=============================================="
info " Useful commands:"
info "  ksql                          → open ksqlDB CLI"
info "  curl localhost:8083/connectors → list connectors"
info "  bash scripts/status.sh        → check all services"
info "  bash scripts/stop.sh          → stop all services"
echo ""
